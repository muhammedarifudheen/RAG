"""A web search before every answer, so the agents see today's facts.

Several sources are searched at once and whatever arrives within the time limit is
used: Tavily or Brave when their key is set (whole-web results), and always, needing no
key, Google News (what happened recently, with dates) and Wikipedia (current articles).
"""

from __future__ import annotations

import html
import logging
import queue
import re
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from email.utils import parsedate_to_datetime

import httpx2

logger = logging.getLogger("atlas.api.assistant")

USER_AGENT = "Atlas/1.0 (https://github.com/muhammedarifudheen/RAG)"
GOOGLE_NEWS = "https://news.google.com/rss/search"
WIKIPEDIA = "https://en.wikipedia.org/w/api.php"
TAVILY = "https://api.tavily.com/search"
BRAVE = "https://api.search.brave.com/res/v1/web/search"


@dataclass(frozen=True)
class WebResult:
    title: str
    url: str
    text: str
    source: str  # which search found it
    published: str | None = None  # YYYY-MM-DD, when known


_TAG = re.compile(r"<[^>]+>")
_ITEM = re.compile(r"<item>(.*?)</item>", re.DOTALL)
_STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "i",
        "in",
        "is",
        "it",
        "its",
        "me",
        "my",
        "of",
        "on",
        "or",
        "please",
        "should",
        "tell",
        "that",
        "the",
        "their",
        "there",
        "this",
        "to",
        "was",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "whose",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "about",
        "explain",
        "give",
        "show",
        "work",
        "works",
        "mean",
        "means",
        "meaning",
        "define",
        "definition",
        "example",
        "examples",
        "difference",
        "between",
        "use",
        "used",
        "using",
        "briefly",
        "simple",
        "simply",
        "like",
        "much",
        "many",
        "some",
        "any",
        "get",
        "know",
        "need",
        "want",
    ]
)


def _field(item: str, name: str) -> str:
    found = re.search(rf"<{name}[^>]*>(.*?)</{name}>", item, re.DOTALL)
    if not found:
        return ""
    value = found.group(1).replace("<![CDATA[", "").replace("]]>", "")
    return html.unescape(_TAG.sub(" ", html.unescape(value))).strip()


def _day(value: str) -> str | None:
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError):
        return None


def keywords(question: str, limit: int = 12) -> str:
    """The words of a question that matter to a keyword search."""
    words = re.findall(r"[\w+#.'-]+", question.lower())
    kept = [w.strip(".'") for w in words if w.strip(".'") and w not in _STOP]
    return " ".join(kept[:limit]) or question[:200]


class WebSearch:
    def __init__(
        self,
        client: httpx2.Client,
        *,
        tavily_key: str | None = None,
        brave_key: str | None = None,
        news: bool = True,
        wikipedia: bool = True,
        max_wait: float = 5.0,
        per_source: int = 5,
    ) -> None:
        self.client = client
        self.max_wait = max_wait
        self.per_source = per_source
        self.searches: list[Callable[[str], list[WebResult]]] = []
        if tavily_key:
            self.tavily_key = tavily_key
            self.searches.append(self.tavily)
        if brave_key:
            self.brave_key = brave_key
            self.searches.append(self.brave)
        if news:
            self.searches.append(self.news)
        if wikipedia:
            self.searches.append(self.wikipedia)

    def search(self, query: str, recent: bool = False) -> list[WebResult]:
        """Every source at once, using the ones that answered within `max_wait` seconds.
        Keyed whole-web results come first; then, for a question about what is happening
        now (`recent`), the news before Wikipedia, otherwise Wikipedia before the news."""
        searches = list(self.searches)
        if not recent and self.news in searches and self.wikipedia in searches:
            searches.remove(self.wikipedia)
            searches.insert(searches.index(self.news), self.wikipedia)
        found: queue.Queue = queue.Queue()

        def run(index: int, search: Callable[[str], list[WebResult]]) -> None:
            started = time.monotonic()
            try:
                found.put((index, search(query)))
            except (httpx2.HTTPError, ValueError, KeyError) as error:
                logger.info(
                    "web search %s failed in %.1fs (%s)",
                    search.__name__,
                    time.monotonic() - started,
                    error,
                )
                found.put((index, []))

        for index, search in enumerate(searches):
            threading.Thread(target=run, args=(index, search), daemon=True).start()
        deadline = time.monotonic() + self.max_wait
        by_source: dict[int, list[WebResult]] = {}
        for _ in searches:
            try:
                index, results = found.get(timeout=max(0.0, deadline - time.monotonic()))
            except queue.Empty:
                break
            by_source[index] = results
        seen: set[str] = set()
        merged: list[WebResult] = []
        for index in sorted(by_source):
            for result in by_source[index]:
                if result.url not in seen:
                    seen.add(result.url)
                    merged.append(result)
        return merged

    def tavily(self, query: str) -> list[WebResult]:
        response = self.client.post(
            TAVILY,
            json={
                "api_key": self.tavily_key,
                "query": query[:400],
                "max_results": self.per_source,
                "search_depth": "basic",
            },
            timeout=self.max_wait,
        )
        response.raise_for_status()
        return [
            WebResult(r["title"], r["url"], (r.get("content") or "")[:1500], "Tavily")
            for r in response.json().get("results", [])
        ]

    def brave(self, query: str) -> list[WebResult]:
        response = self.client.get(
            BRAVE,
            params={"q": query[:400], "count": self.per_source},
            headers={"X-Subscription-Token": self.brave_key, "Accept": "application/json"},
            timeout=self.max_wait,
        )
        response.raise_for_status()
        results = (response.json().get("web") or {}).get("results", [])
        return [
            WebResult(
                r["title"],
                r["url"],
                _TAG.sub(
                    "", " ".join([r.get("description") or "", *(r.get("extra_snippets") or [])])
                )[:1500],
                "Brave",
                r.get("page_age", "")[:10] or None,
            )
            for r in results
        ]

    def news(self, query: str) -> list[WebResult]:
        response = self.client.get(
            GOOGLE_NEWS,
            params={"q": keywords(query), "hl": "en-US", "gl": "US", "ceid": "US:en"},
            headers={"User-Agent": USER_AGENT},
            timeout=self.max_wait,
        )
        response.raise_for_status()
        results = []
        for item in _ITEM.findall(response.text):
            title, link = _field(item, "title"), _field(item, "link")
            if not (title and link):
                continue
            publisher = _field(item, "source")
            results.append(
                WebResult(
                    title,
                    link,
                    f"{title} ({publisher})" if publisher else title,
                    "Google News",
                    _day(_field(item, "pubDate")),
                )
            )
        # Google's most relevant few, newest first: what is true now leads.
        relevant = results[: self.per_source + 3]
        relevant.sort(key=lambda r: r.published or "", reverse=True)
        return relevant

    def wikipedia(self, query: str) -> list[WebResult]:
        response = self.client.get(
            WIKIPEDIA,
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": keywords(query),
                "gsrlimit": 3,
                "prop": "extracts|info",
                "explaintext": 1,
                "exintro": 1,
                "exchars": 1500,
                "inprop": "url",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=self.max_wait,
        )
        response.raise_for_status()
        pages = (response.json().get("query") or {}).get("pages") or {}
        ranked = sorted(pages.values(), key=lambda p: p.get("index", 0))
        return [
            WebResult(
                p["title"],
                p["fullurl"],
                (p.get("extract") or "").strip(),
                "Wikipedia",
            )
            for p in ranked
            if p.get("extract")
        ]


def web_block(results: Sequence[WebResult], today: date, limit: int = 9000) -> str:
    """The results as the agents see them, numbered, within `limit` characters."""
    lines = [f'<web_results searched="{today.isoformat()}">']
    used = len(lines[0])
    for n, result in enumerate(results, 1):
        dated = f", {result.published}" if result.published else ""
        entry = f"[{n}] {result.title} ({result.source}{dated})\n{result.url}\n{result.text}\n"
        if used + len(entry) > limit:
            break
        lines.append(entry)
        used += len(entry)
    lines.append("</web_results>")
    return "\n".join(lines)


_FOLLOW_UP = re.compile(
    r"^(and|or|but|also|what about|how about|in|for|with|then|so|same|why|how come)\b|"
    r"\b(it|its|that|this|they|them|those|these|he|she|him|her)\b",
    re.IGNORECASE,
)


def search_query(question: str, previous: str | None) -> str:
    """What to search for: the question, with the previous one for a follow-up that
    means nothing alone, such as "and in Go?" or "when was it released?"."""
    question = question.strip()
    if previous and len(question) < 60 and _FOLLOW_UP.search(question):
        return f"{previous.strip()[:200]} {question}"
    return question[:400]
