"""The web search before every answer, the quicker council, and routing questions about now."""

import time
from datetime import date
from types import SimpleNamespace

import httpx2

from app.assistant.router import classify
from app.assistant.service import Assistant, rest_after
from app.assistant.web import WebResult, WebSearch, keywords, search_query, web_block

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Python 3.14.5 released - igor&#39;s LAB</title>
<link>https://news.example/old</link><pubDate>Mon, 11 May 2026 08:00:00 GMT</pubDate>
<source url="https://igor.example">igor's LAB</source></item>
<item><title>Python 3.15 Released with Faster JIT - Linuxiac</title>
<link>https://news.example/new</link><pubDate>Sat, 10 Oct 2026 09:30:00 GMT</pubDate>
<source url="https://linuxiac.example">Linuxiac</source></item>
</channel></rss>"""

WIKI = {
    "query": {
        "pages": {
            "2": {
                "index": 2,
                "title": "History of Python",
                "fullurl": "https://en.wikipedia.org/wiki/History_of_Python",
                "extract": "Python was conceived in the late 1980s.",
            },
            "1": {
                "index": 1,
                "title": "Python (programming language)",
                "fullurl": "https://en.wikipedia.org/wiki/Python_(programming_language)",
                "extract": "Python is a high-level language. Python 3.15 is the latest.",
            },
            "3": {"index": 3, "title": "Empty", "fullurl": "https://x", "extract": ""},
        }
    }
}


class Web:
    """An HTTP client answering like Google News, Wikipedia, Tavily and Brave."""

    def __init__(self, slow=0.0, fail=()):
        self.slow, self.fail, self.calls = slow, fail, []

    def _reply(self, url, *, text="", data=None):
        self.calls.append(url)
        if any(part in url for part in self.fail):
            raise httpx2.ConnectError("down")
        if "wikipedia" in url and self.slow:
            time.sleep(self.slow)
        return SimpleNamespace(raise_for_status=lambda: None, text=text, json=lambda: data or {})

    def get(self, url, params=None, headers=None, timeout=None):
        if "news.google" in url:
            return self._reply(url, text=RSS)
        if "brave" in url:
            data = {
                "web": {
                    "results": [
                        {"title": "Brave hit", "url": "https://b", "description": "<b>B</b>"}
                    ]
                }
            }
            return self._reply(url, data=data)
        return self._reply(url, data=WIKI)

    def post(self, url, json=None, timeout=None):
        data = {"results": [{"title": "Tavily hit", "url": "https://t", "content": "T"}]}
        return self._reply(url, data=data)


def test_google_news_results_come_newest_first_with_their_dates():
    results = WebSearch(Web(), wikipedia=False).search("latest python")
    assert [r.url for r in results] == ["https://news.example/new", "https://news.example/old"]
    assert results[0].published == "2026-10-10"
    assert results[0].source == "Google News"
    assert "Linuxiac" in results[0].text
    assert results[1].title == "Python 3.14.5 released - igor's LAB"


def test_wikipedia_articles_keep_the_search_order_and_skip_empty_ones():
    results = WebSearch(Web(), news=False).search("python")
    assert [r.title for r in results] == ["Python (programming language)", "History of Python"]
    assert results[0].text.startswith("Python is a high-level language")


def test_keyed_searches_come_first_when_their_keys_are_set():
    results = WebSearch(Web(), tavily_key="t", brave_key="b").search("python")
    assert [r.source for r in results[:2]] == ["Tavily", "Brave"]
    assert results[1].text == "B"
    assert {r.source for r in results} == {"Tavily", "Brave", "Google News", "Wikipedia"}


def test_news_leads_for_questions_about_now_and_wikipedia_otherwise():
    search = WebSearch(Web())
    assert search.search("latest python", recent=True)[0].source == "Google News"
    assert search.search("explain python", recent=False)[0].source == "Wikipedia"


def test_the_news_kept_are_googles_most_relevant_then_sorted_by_date():
    items = "".join(
        f"<item><title>T{n}</title><link>https://n/{n}</link>"
        f"<pubDate>Mon, {n:02d} Jan 2024 00:00:00 GMT</pubDate></item>"
        for n in range(1, 21)
    )
    web = Web()
    web.get = lambda url, params=None, headers=None, timeout=None: SimpleNamespace(
        raise_for_status=lambda: None, text=f"<rss>{items}</rss>"
    )
    results = WebSearch(web, wikipedia=False, per_source=2).search("q")
    # The first five Google listed (T1-T5), the newest of those first.
    assert [r.title for r in results] == ["T5", "T4", "T3", "T2", "T1"]


def test_a_failing_or_slow_source_does_not_hold_up_the_rest():
    web = Web(slow=2.0, fail=("news.google",))
    started = time.monotonic()
    results = WebSearch(web, max_wait=0.3, tavily_key="t").search("python")
    assert time.monotonic() - started < 1.5
    assert [r.source for r in results] == ["Tavily"]


def test_keywords_drop_the_little_words():
    assert (
        keywords("What is the latest stable version of Python?") == "latest stable version python"
    )
    assert keywords("C++ vs C# in 2026") == "c++ vs c# 2026"


def test_a_short_follow_up_is_searched_with_the_question_before_it():
    assert search_query("and in Go?", "How do I read a file in Python?") == (
        "How do I read a file in Python? and in Go?"
    )
    assert search_query("What is new in Python 3.15?", "hello") == "What is new in Python 3.15?"


def test_the_results_are_numbered_dated_and_kept_within_the_limit():
    results = [
        WebResult("New", "https://n", "Fresh news.", "Google News", "2026-10-10"),
        WebResult("Wiki", "https://w", "An article.", "Wikipedia"),
        WebResult("Long", "https://l", "x" * 5000, "Wikipedia"),
    ]
    block = web_block(results, date(2026, 10, 24), limit=1000)
    assert block.startswith('<web_results searched="2026-10-24">')
    assert "[1] New (Google News, 2026-10-10)\nhttps://n\nFresh news." in block
    assert "[2] Wiki (Wikipedia)\nhttps://w" in block
    assert "[3]" not in block
    assert block.endswith("</web_results>")


# --- The assistant with a web search -----------------------------------------------------


class Agent:
    def __init__(self, name, replies):
        self.name, self.label = name, name.title()
        self.replies = dict(replies)
        self.models = list(self.replies)
        self.calls = []

    def searches(self, model):
        return False

    def stream(self, model, system, turns, outcome, *, web, temperature=None):
        self.calls.append(SimpleNamespace(model=model, system=system, turns=turns))
        reply = self.replies[model]
        if isinstance(reply, Exception):
            raise reply
        outcome.model = model
        yield reply


class Searcher:
    def __init__(self):
        self.queries = []

    def search(self, query, recent=False):
        self.queries.append((query, recent))
        return [
            WebResult(
                "Python 3.15 released", "https://news/315", "Out now.", "Google News", "2026-10-10"
            )
        ]


def test_every_agent_sees_the_web_results_and_the_answer_links_them():
    searcher = Searcher()
    gemini = Agent("gemini", {"g1": "Python 3.15 is the latest."})
    assistant = Assistant([gemini], web=searcher)
    events = list(assistant.respond("What is the latest Python?", [], ()))
    names = [name for name, _ in events]
    assert names[:3] == ["route", "searching", "web"]
    assert events[2][1]["sources"] == [{"title": "Python 3.15 released", "url": "https://news/315"}]
    assert searcher.queries == [("What is the latest Python?", True)]
    asked = gemini.calls[0].turns[-1].content
    assert "<web_results" in asked and "https://news/315" in asked
    assert asked.rstrip().endswith("What is the latest Python?")
    assert events[-1][1]["web_sources"] == [
        {"title": "Python 3.15 released", "url": "https://news/315"}
    ]


def test_small_talk_is_not_searched():
    searcher = Searcher()
    assistant = Assistant([Agent("groq", {"q1": "Hi there!"})], web=searcher)
    names = [name for name, _ in assistant.respond("hello", [], ())]
    assert "searching" not in names
    assert searcher.queries == []


def test_the_council_gives_the_web_results_to_every_agent_and_lists_them():
    searcher = Searcher()
    gemini = Agent("gemini", {"g1": "Draft one."})
    groq = Agent("groq", {"q1": "Draft two."})
    assistant = Assistant([gemini, groq], web=searcher, council_size=12, council_grace=0.2)
    events = list(assistant.respond("What is the latest Python?", [], ()))
    for agent in (gemini, groq):
        assert "<web_results" in agent.calls[0].turns[-1].content
    assert events[-1][0] == "done"
    assert {"title": "Python 3.15 released", "url": "https://news/315"} in events[-1][1][
        "web_sources"
    ]


def test_the_quickest_service_merges_first():
    gemini = Agent("gemini", {"g1": "Gemini's draft."})
    groq = Agent("groq", {"q1": "Groq's draft."})
    assistant = Assistant(
        [gemini, groq], council_size=12, council_grace=0.2, fast_mergers=("groq",)
    )
    events = list(assistant.respond("What is HMAC?", [], ()))
    assert events[-1][0] == "done"
    assert [c.model for c in groq.calls if "Several independent" in c.system] == ["q1"]
    assert not [c for c in gemini.calls if "Several independent" in c.system]


def test_only_the_first_drafts_go_to_the_merge():
    gemini = Agent("gemini", {f"g{i}": f"Draft {i}." for i in range(1, 6)})
    assistant = Assistant([gemini], council_size=12, council_grace=0.5, merge_drafts=3)
    list(assistant.respond("What is HMAC?", [], ()))
    merge = next(c for c in gemini.calls if "Several independent" in c.system)
    assert merge.turns[-1].content.count("<draft n=") == 3


# --- Routing and glitches ----------------------------------------------------------------


def test_questions_about_now_are_current_even_when_they_name_a_language():
    assert classify("What is the latest stable version of Python?", 0.2) == "current"
    assert classify("Any news about React this week?", None) == "current"
    # Code in the question keeps it a code question.
    assert classify("Why does my latest change break `foo()`?", None) == "code"
    assert classify("```py\nprint(1)\n```\nwhy does this fail now?", None) == "code"


def test_a_glitch_in_one_reply_is_retried_not_rested():
    for detail in (
        "Groq g: {'message': 'Tool choice is none, but model called a tool', 'code': 'tool_use_failed'}",
        "Groq g: Parsing failed. The model generated output that could not be parsed.",
        "OpenRouter m: Provider returned error",
    ):
        assert rest_after(detail) == 0
        from app.assistant.service import _BUSY

        assert _BUSY.search(detail)


class SlowAgent(Agent):
    def __init__(self, name, replies, delay):
        super().__init__(name, replies)
        self.delay = delay

    def stream(self, model, system, turns, outcome, *, web, temperature=None):
        if "Several independent" not in system:
            time.sleep(self.delay)
        yield from super().stream(model, system, turns, outcome, web=web)


def test_the_agent_that_answered_quickest_merges():
    gemini = SlowAgent("gemini", {"g1": "Gemini's draft."}, delay=0.3)
    nvidia = SlowAgent("nvidia", {"n1": "NVIDIA's draft."}, delay=0.0)
    assistant = Assistant([gemini, nvidia], council_size=12, council_grace=1.0, merge_by_speed=True)
    events = list(assistant.respond("What is HMAC?", [], ()))
    assert events[-1][0] == "done"
    assert [c.model for c in nvidia.calls if "Several independent" in c.system] == ["n1"]


def test_the_merger_gets_the_web_results_links_but_not_their_text():
    searcher = Searcher()
    gemini = Agent("gemini", {"g1": "Draft one."})
    groq = Agent("groq", {"q1": "Draft two."})
    assistant = Assistant([gemini, groq], web=searcher, council_size=12, council_grace=0.2)
    list(assistant.respond("What is the latest Python?", [], ()))
    merges = [c for a in (gemini, groq) for c in a.calls if "Several independent" in c.system]
    asked = merges[0].turns[-1].content
    assert "https://news/315" in asked
    assert "Out now." not in asked
    # The agents themselves read the full results.
    assert "Out now." in gemini.calls[0].turns[-1].content
