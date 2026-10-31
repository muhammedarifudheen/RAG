"""Speed and trust: hybrid search, its fallback, the caches, confidence and stage timings."""

import json
from types import SimpleNamespace

from app.assistant.cache import TTLCache, answer_cacheable
from app.assistant.confidence import confidence, coverage
from app.assistant.service import Assistant, Options
from app.schemas import Citation, CodeChunk


def chunk(symbol_id=1, score=0.8, relevance=None):
    return CodeChunk(
        symbol_id=symbol_id,
        name="unsign",
        kind="method",
        file="a/signer.py",
        language="python",
        start_line=10,
        end_line=20,
        signature=None,
        score=score,
        snippet="def unsign(self):\n    pass",
        snippet_end_line=20,
        truncated=False,
        citation="[a/signer.py:10-20]",
        relevance=relevance,
    )


def cite(verified=True):
    return Citation(
        ref="[a/signer.py:10-20]", file="a/signer.py", start_line=10, end_line=20, verified=verified
    )


# --- caches ------------------------------------------------------------------------------


def test_entries_expire_and_the_least_recently_used_go_first():
    now = [0.0]
    store: TTLCache[int] = TTLCache(2, ttl=10, clock=lambda: now[0])
    store.put("a", 1)
    store.put("b", 2)
    assert store.get("a") == 1  # a is now the most recently used
    store.put("c", 3)
    assert store.get("b") is None and store.get("a") == 1 and store.get("c") == 3
    now[0] = 11
    assert store.get("a") is None


def test_only_lasting_answers_are_cached():
    good = {"complete": True, "route": "sources", "answer": "A.", "web_sources": []}
    assert answer_cacheable(good)
    assert not answer_cacheable({**good, "route": "current"})  # the latest, every time
    assert not answer_cacheable({**good, "web_sources": [{"title": "t", "url": "u"}]})
    assert not answer_cacheable({**good, "complete": False})


class Judge:
    def __init__(self):
        self.name, self.label, self.models, self.calls = "nvidia", "NVIDIA", ["n1"], 0

    def searches(self, model):
        return False

    def stream(self, model, system, turns, outcome, *, web, temperature=None, max_tokens=None):
        self.calls += 1
        outcome.model = model
        yield '{"score": 8, "reason": "close"}'


def test_the_judges_verdicts_are_kept_per_question_and_excerpt():
    judge = Judge()
    assistant = Assistant([judge], reranker=True)
    first = assistant.judge_chunks("How is it  signed?", [chunk(1), chunk(2, 0.7)])
    again = assistant.judge_chunks("how is it signed?", [chunk(1), chunk(2, 0.7)])
    assert first == again == {1: (8, "close"), 2: (8, "close")}
    assert judge.calls == 2  # the second time, nothing is asked again


# --- confidence --------------------------------------------------------------------------


def test_coverage_counts_cited_sentences():
    answer = (
        "It splits the value at the separator [a/signer.py:10-20]. "
        "Then it compares the signatures in constant time. "
        "Older keys in the list still verify it [a/signer.py:10-20]."
    )
    assert round(coverage(answer), 2) == 0.67


def test_confidence_comes_from_relevance_coverage_and_checked_citations():
    cited = "It splits the value at the separator in two [a/signer.py:10-20]."
    high = confidence(cited, [chunk(relevance=9)], [cite()])
    assert high.level == "high" and high.verified == 1
    assert confidence(cited, [chunk(relevance=2)], [cite()]).level == "low"
    assert confidence(cited, [chunk(relevance=9)], [cite(False)]).level == "low"
    uncited = "It splits the value at the separator in two. It compares in constant time."
    assert confidence(uncited, [chunk(relevance=9)], []).level == "low"
    assert confidence(cited, [], [cite()]) is None  # general knowledge: no rating


# --- the assistant's report --------------------------------------------------------------


class Answerer:
    def __init__(self):
        self.name, self.label, self.models = "gemini", "Gemini", ["g1"]

    def searches(self, model):
        return False

    def stream(self, model, system, turns, outcome, *, web, temperature=None, max_tokens=None):
        outcome.model = model
        yield "It splits the value at the separator in two [a/signer.py:10-20]."


def test_an_answer_reports_its_notice_stage_timings_and_confidence(caplog):
    caplog.set_level("INFO", logger="atlas.api.assistant")
    events = list(
        Assistant([Answerer()]).respond(
            "How is it signed?",
            [chunk(relevance=9)],
            (),
            "auto",
            Options(
                notice="Retrieval failed, so this answer used keyword search.",
                timings={"search": 0.05},
            ),
        )
    )
    assert (
        "notice",
        {"message": "Retrieval failed, so this answer used keyword search."},
    ) in events
    done = events[-1][1]
    assert set(done["timings"]) == {"search", "answer"}
    assert done["notice"].startswith("Retrieval failed")
    assert done["confidence"]["level"] == "high"
    logged = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("answer {"))
    record = json.loads(logged.removeprefix("answer "))
    assert record["retrieved"] == [1] and record["verified"] == 1
    assert record["confidence"] == "high" and "answer" in record["timings"]


# --- through /ask and the database -------------------------------------------------------


def test_keyword_search_finds_identifiers_by_their_words(db):
    from seed import FakeEmbedder

    from app.services.search import hybrid_search, keyword_symbols

    found = keyword_symbols(db, "format name", 5, 30)
    assert found and found[0].name == "format_name"
    fused, notice = hybrid_search(db, FakeEmbedder(), "format name", 5, 30)
    assert notice is None and any(c.name == "format_name" for c in fused)


def test_a_failed_vector_search_falls_back_to_keywords(db):
    from app.services.search import hybrid_search

    class Broken:
        def embed(self, text):
            raise RuntimeError("the embedding model is not loaded")

    found, notice = hybrid_search(db, Broken(), "format name", 5, 30)
    assert notice == "Retrieval failed, so this answer used keyword search."
    assert found[0].name == "format_name"


def test_a_repeated_question_is_answered_from_the_cache(client):
    from app.assistant import get_assistant
    from app.main import app

    calls = []

    class Counting(Answerer):
        def stream(self, *args, **kwargs):
            calls.append(1)
            yield from super().stream(*args, **kwargs)

    assistant = Assistant([Counting()], answer_cache=True)
    app.dependency_overrides[get_assistant] = lambda: assistant
    try:
        body = {"question": "format name of a user", "style": "concise"}
        first = client.post("/ask", json=body).json()
        second = client.post("/ask", json=body).json()
        fresh = client.post("/ask", json={**body, "cache": False}).json()
        regenerated = client.post("/ask", json=body, headers={"X-Atlas-Fresh": "true"}).json()
    finally:
        app.dependency_overrides.pop(get_assistant, None)
    assert first["cached"] is False and second["cached"] is True
    assert second["answer"] == first["answer"]
    assert fresh["cached"] is False
    assert regenerated["cached"] is False
    assert len(calls) == 3  # the first, the fresh one and the regenerated one


def test_the_assistant_gets_five_excerpts_unless_asked(client):
    from app.assistant import get_assistant
    from app.main import app

    seen = []

    class Recording(Answerer):
        def stream(self, model, system, turns, outcome, *, web, temperature=None, max_tokens=None):
            seen.append(turns[-1].content)
            yield from super().stream(
                model, system, turns, outcome, web=web, temperature=temperature
            )

    app.dependency_overrides[get_assistant] = lambda: Assistant([Recording()], min_score=0.0)
    try:
        body = client.post(
            "/ask", json={"question": "format name of a user", "style": "concise"}
        ).json()
    finally:
        app.dependency_overrides.pop(get_assistant, None)
    assert len(body["chunks"]) == 5
    assert body["timings"].keys() >= {"search", "answer"}
    assert SimpleNamespace  # keeps the import for the fakes above


def test_citations_in_code_spans_or_with_odd_dashes_become_citations():
    from app.services.search import tidy_citations

    shown = [chunk()]
    answer = (
        "It checks in `a/signer.py:10‑20` and [a/signer.py:12–15], "
        "not `other.py:1-2` or `x = a[1:2]`."
    )
    assert tidy_citations(answer, shown) == (
        "It checks in [a/signer.py:10-20] and [a/signer.py:12-15], "
        "not `other.py:1-2` or `x = a[1:2]`."
    )


def test_citations_in_html_code_tags_inside_brackets_become_citations():
    from app.services.search import tidy_citations

    answer = "| 1 | Calls unsign | [<code>a/signer.py:10-20</code>] |"
    assert tidy_citations(answer, [chunk()]) == "| 1 | Calls unsign | [a/signer.py:10-20] |"


def test_a_zero_width_space_inside_a_citation_is_dropped():
    from app.services.search import tidy_citations

    assert tidy_citations("It decodes [\u200ba/signer.py:10-20].", [chunk()]) == (
        "It decodes [a/signer.py:10-20]."
    )
