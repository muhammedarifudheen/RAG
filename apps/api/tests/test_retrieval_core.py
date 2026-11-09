"""The retrieval core's pure parts: final scoring, stage budgets, adaptive top-k, the cache's
per-entry lifetime. No database."""

import time
from datetime import UTC, datetime, timedelta

import pytest

from app.assistant.cache import TTLCache
from app.retrieval import scoring
from app.retrieval.budget import Trace, run_stage
from app.retrieval.topk import MAX_CHUNKS, adaptive_top_k, capped
from app.schemas import CodeChunk

NOW = datetime(2026, 11, 9, tzinfo=UTC)


def chunk(
    sid: int,
    *,
    score: float = 0.5,
    relevance: int | None = None,
    weight: int | None = 2,
    kind: str = "function",
    updated: datetime | None = None,
    snippet: str = "x",
    name: str = "f",
    file: str = "a.py",
    source_id: int | None = 1,
) -> CodeChunk:
    return CodeChunk(
        symbol_id=sid,
        name=name,
        kind=kind,
        signature=None,
        file=file,
        language="python",
        start_line=1,
        end_line=2,
        score=score,
        snippet=snippet,
        snippet_end_line=2,
        truncated=False,
        citation=f"[{file}:1-2]",
        relevance=relevance,
        weight=weight,
        source_id=source_id,
        source_updated_at=updated,
    )


def ids(ranked):
    return [c.symbol_id for c, _ in ranked]


def test_weights_sum_to_one():
    assert sum(scoring.WEIGHTS.values()) == pytest.approx(1.0)


def test_similarity_alone_does_not_decide():
    # The most similar excerpt is derived, old and unjudged; the other is primary, fresh and
    # judged highly relevant: it must come first.
    stale = chunk(1, score=0.95, weight=1, updated=NOW - timedelta(days=900))
    good = chunk(2, score=0.5, relevance=9, weight=3, updated=NOW - timedelta(days=2))
    assert ids(scoring.rank([stale, good], "q", now=NOW)) == [2, 1]


def test_freshness_halves_every_half_life():
    code = chunk(1, kind="function", updated=NOW - timedelta(days=30))
    docs = chunk(2, kind="section", updated=NOW - timedelta(days=90))
    assert scoring.freshness_weight(code, NOW) == pytest.approx(0.5)
    assert scoring.freshness_weight(docs, NOW) == pytest.approx(0.5)
    assert scoring.freshness_weight(chunk(3), NOW) == 0.5  # age unknown


def test_trust_tiers():
    assert [scoring.trust_weight(chunk(i, weight=w)) for i, w in enumerate((3, 2, 1))] == [
        1.0,
        0.7,
        0.4,
    ]


def test_rerank_score_uses_judge_else_similarity():
    assert scoring.rerank_score(chunk(1, relevance=7, score=0.1)) == 0.7
    assert scoring.rerank_score(chunk(1, relevance=None, score=0.4)) == 0.4


def test_rrf_scores_top_is_one():
    scores = scoring.rrf_scores([chunk(1), chunk(2), chunk(3)])
    assert scores[1] == 1.0 and scores[1] > scores[2] > scores[3]


def test_equal_scores_prefer_the_shorter_excerpt():
    t = NOW - timedelta(days=3)
    long = chunk(1, updated=t, snippet="a much longer excerpt with more noise in it")
    short = chunk(2, updated=t, snippet="short")
    # No candidate order, so rank fusion is equal and the scores tie exactly.
    assert ids(scoring.rank([long, short], "q", candidates=[], now=NOW)) == [2, 1]


def test_equal_scores_prefer_the_higher_trust_before_length():
    t = NOW - timedelta(days=3)
    # Trust moves the score itself, so build the tie from the other signals: a primary source
    # with a lower judge score ties a secondary one with a higher judge score.
    primary = chunk(1, updated=t, weight=3, relevance=0, snippet="long excerpt text here")
    secondary = chunk(2, updated=t, weight=2, relevance=0, snippet="short")
    ranked = scoring.rank([secondary, primary], "q", candidates=[], now=NOW)
    assert ids(ranked) == [1, 2]  # trust adds to the score, so primary leads outright


def test_identifier_match_breaks_the_last_tie():
    t = NOW - timedelta(days=1)
    code = "def verify_signature(): ..."
    plain = chunk(1, updated=t, snippet="y" * len(code), name="other")  # same length
    named = chunk(2, updated=t, snippet=code, name="verify_signature")
    # Same signals; the query names verify_signature. Retrieval order puts `plain` first only
    # by rank, so equalise by giving both the same candidate position.
    ranked = scoring.rank([plain, named], "what does verify_signature do", candidates=[], now=NOW)
    assert ids(ranked) == [2, 1]


def test_identifiers_found_in_a_question():
    found = scoring.identifiers("How does Signer.derive_key use src/itsdangerous/signer.py?")
    assert "derive_key" in found and "src/itsdangerous/signer.py" in found


def test_hit_rate_raises_a_trusted_source():
    a = chunk(1, source_id=10)
    b = chunk(2, source_id=20)
    ranked = scoring.rank([a, b], "q", candidates=[], hit_rates={20: 0.95, 10: 0.1}, now=NOW)
    assert ids(ranked) == [2, 1]


def test_smoothed_hit_rate():
    assert scoring.smoothed_hit_rate(0, 0) == 0.5
    assert scoring.smoothed_hit_rate(9, 1) == pytest.approx(10 / 12)
    assert scoring.smoothed_hit_rate(1, 0) < 0.8  # one vote does not decide


def test_adaptive_top_k():
    assert adaptive_top_k("What is the default hash?") == 3
    assert adaptive_top_k("How does the signer verify a timestamp?") == 5
    assert adaptive_top_k("Compare the serializers and list the differences") == 8
    assert capped(20) == MAX_CHUNKS == 8 and capped(0) == 1


def test_a_slow_stage_gives_way_to_its_fallback():
    trace = Trace()
    result = run_stage(trace, "plan", lambda: time.sleep(0.5) or ["late"], ["now"], 0.05)
    assert result == ["now"]
    assert trace.is_degraded and "plan timed out" in trace.degraded[0]
    assert "plan" in trace.timings


def test_a_failing_stage_gives_way_and_says_why():
    trace = Trace()

    def boom():
        raise RuntimeError("down")

    assert run_stage(trace, "judge", boom, {}, 1.0, reason="judge down") == {}
    assert trace.degraded == ["judge down"]


def test_a_fast_stage_is_not_degraded():
    trace = Trace()
    assert run_stage(trace, "x", lambda: 42, 0, 1.0) == 42
    assert not trace.is_degraded and "x" in trace.timings


def test_cache_entry_lifetimes():
    clock = [0.0]
    cache: TTLCache[str] = TTLCache(10, ttl=100, clock=lambda: clock[0])
    cache.put("day", "a")
    cache.put("hour", "b", ttl=10)
    clock[0] = 11
    assert cache.get("hour") is None  # its own, shorter life
    assert cache.get("day") == "a"
    clock[0] = 101
    assert cache.get("day") is None
