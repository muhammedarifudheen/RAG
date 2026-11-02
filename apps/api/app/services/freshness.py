"""Freshness: how current an excerpt's source is, and so an answer.

FRESH within a third of the threshold since it was ingested, RECENT within the
threshold, STALE beyond it. Thresholds by kind of source (configurable): code 30 days,
documentation 90, news 7. An answer is as fresh as the freshest source it used; a STALE
answer opens with a warning, and the footer always carries its freshness."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from urllib.parse import urlparse

from app.config import settings
from app.schemas import CodeChunk

LABELS = ("fresh", "recent", "stale")
_CODE = (".py", ".ts", ".mts", ".cts", ".tsx", ".go")
_NEWS = re.compile(
    r"(^|\.)(reuters\.com|apnews\.com|bbc\.co\.uk|bbc\.com|nytimes\.com|theguardian\.com|"
    r"cnn\.com|aljazeera\.com|bloomberg\.com|techcrunch\.com|theverge\.com|arstechnica\.com|"
    r"news\.ycombinator\.com|wired\.com|ft\.com|wsj\.com)$|(^|\.)news\."
)


def category(kind: str | None, url: str | None, path: str) -> str:
    """code, news or docs."""
    if kind == "repo" or path.lower().endswith(_CODE):
        return "code"
    host = (urlparse(url).hostname or "").lower() if url else ""
    if host and _NEWS.search(host):
        return "news"
    return "docs"


def threshold(kind: str) -> int:
    return {
        "code": settings.freshness_code_days,
        "news": settings.freshness_news_days,
    }.get(kind, settings.freshness_docs_days)


def label(ingested: datetime | None, kind: str, now: datetime | None = None) -> str | None:
    """fresh, recent or stale, by days since it was ingested; None if unknown."""
    if ingested is None:
        return None
    now = now or datetime.now(UTC)
    if ingested.tzinfo is None:
        ingested = ingested.replace(tzinfo=UTC)
    age = (now - ingested).total_seconds() / 86400
    limit = threshold(kind)
    if age <= limit / 3:
        return "fresh"
    return "recent" if age <= limit else "stale"


def answer_freshness(chunks: Sequence[dict], files: set[str]) -> dict | None:
    """The answer's freshness: that of the freshest source among those it used (`files`,
    or every excerpt if none were cited). None if no excerpt carries a date."""
    used = [c for c in chunks if c.get("file") in files] or list(chunks)
    rated = [c for c in used if c.get("freshness") and c.get("ingested_at")]
    if not rated:
        return None
    best = min(rated, key=lambda c: LABELS.index(c["freshness"]))
    newest = max(c["ingested_at"] for c in rated if c["freshness"] == best["freshness"])
    return {"label": best["freshness"], "ingested_at": newest}


def stale_warning(ingested_at: str | datetime) -> str:
    when = ingested_at if isinstance(ingested_at, str) else ingested_at.isoformat()
    return f"⚠ This may be outdated — last ingested {when[:10]}."


def prefer_newer(chunks: list[CodeChunk], tie: float = 0.01) -> list[CodeChunk]:
    """When two neighbouring excerpts score alike (within `tie`) and were judged alike,
    the one whose source changed more recently goes first. Otherwise the order stands."""
    out = list(chunks)

    def when(chunk: CodeChunk) -> datetime:
        stamp = chunk.source_updated_at or chunk.ingested_at
        if stamp is None:
            return datetime.min.replace(tzinfo=UTC)
        return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)

    for _ in range(len(out)):
        swapped = False
        for i in range(len(out) - 1):
            a, b = out[i], out[i + 1]
            if a.relevance == b.relevance and abs(a.score - b.score) <= tie and when(b) > when(a):
                out[i], out[i + 1] = b, a
                swapped = True
        if not swapped:
            break
    return out
