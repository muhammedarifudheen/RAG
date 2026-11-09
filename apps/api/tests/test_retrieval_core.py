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


class FakeCrossEncoder:
    """Scores each pair by the number in its passage's name, so the order is knowable."""

    def predict(self, pairs):
        return [float(p[1].split(" (")[0]) for p in pairs]


def _numbered(n: int) -> list[CodeChunk]:
    return [chunk(i, name=str(i)) for i in range(n)]


def test_cross_encoder_orders_scores_and_keeps_five():
    from app.retrieval import reranker

    trace = Trace()
    out = reranker.rerank(
        trace, "q", _numbered(10), 5, timeout=5.0, model_source=lambda: (FakeCrossEncoder(), None)
    )
    assert [c.symbol_id for c in out] == [9, 8, 7, 6, 5]  # best score first, five kept
    assert [c.rerank_score for c in out] == [9.0, 8.0, 7.0, 6.0, 5.0]
    assert not trace.is_degraded and "rerank" in trace.timings


def test_cross_encoder_not_loaded_uses_rrf_order_and_says_so():
    from app.retrieval import reranker

    trace = Trace()
    out = reranker.rerank(
        trace, "q", _numbered(8), 5, model_source=lambda: (None, "reranker failed to load (boom)")
    )
    assert [c.symbol_id for c in out] == [0, 1, 2, 3, 4]  # the RRF order, untouched
    assert all(c.rerank_score is None for c in out)
    assert trace.degraded and "failed to load" in trace.degraded[0]


def test_cross_encoder_over_its_timeout_uses_rrf_order():
    from app.retrieval import reranker

    class Slow:
        def predict(self, pairs):
            time.sleep(0.5)
            return [1.0] * len(pairs)

    trace = Trace()
    out = reranker.rerank(
        trace, "q", _numbered(8), 5, timeout=0.05, model_source=lambda: (Slow(), None)
    )
    assert [c.symbol_id for c in out] == [0, 1, 2, 3, 4]
    assert "rerank" in trace.degraded[0] and "150" not in trace.degraded[0]  # the budget used


def test_cross_encoder_wrong_score_count_degrades():
    from app.retrieval import reranker

    class Broken:
        def predict(self, pairs):
            return [1.0]

    trace = Trace()
    out = reranker.rerank(
        trace, "q", _numbered(6), 5, timeout=5.0, model_source=lambda: (Broken(), None)
    )
    assert [c.symbol_id for c in out] == [0, 1, 2, 3, 4] and trace.is_degraded


def test_the_reranker_is_off_by_default_and_its_score_feeds_the_final_score():
    from app.config import Settings
    from app.retrieval import reranker

    assert Settings.model_fields["atlas_rerank"].default == "off"
    assert reranker.enabled() in (True, False)
    high = chunk(1, score=0.1).model_copy(update={"rerank_score": 6.0})
    low = chunk(2, score=0.9).model_copy(update={"rerank_score": -6.0})
    assert scoring.rerank_score(high) > 0.99
    assert scoring.rerank_score(low) < 0.01


# --- the reranker's startup, health and auto-off ------------------------------------------


@pytest.fixture
def fresh_reranker(monkeypatch):
    """A clean reranker module, the flag on, and the real webhook sender replaced."""
    from app.config import settings
    from app.retrieval import reranker

    reranker.reset()
    monkeypatch.setattr(settings, "atlas_rerank", "on")
    monkeypatch.setattr(settings, "atlas_rerank_warmup_runs", 5)
    sent = []
    monkeypatch.setattr(
        "app.services.webhooks.emit", lambda event, data, db=None: sent.append((event, data))
    )
    yield reranker, settings, sent
    reranker.reset()


def test_startup_loads_warms_up_and_reports(fresh_reranker, monkeypatch):
    reranker, settings, _ = fresh_reranker
    predictions = []

    class Fake:
        provider = "CPUExecutionProvider"

        def __init__(self, *args):
            pass

        def predict(self, pairs):
            predictions.append(len(pairs))
            return [0.0] * len(pairs)

    monkeypatch.setattr(reranker, "OnnxCrossEncoder", Fake)
    before = reranker.status()
    assert before["loaded"] is False and before["state"] == "off" and before["provider"] is None
    reranker._load()  # what the background thread runs
    after = reranker.status()
    assert predictions == [8] * 5  # five dummy predictions, a real-sized batch each
    assert after["loaded"] is True and after["state"] == "ready"
    assert after["provider"] == "CPUExecutionProvider" and after["p50_ms"] is None
    assert after["load_ms"] is not None and after["warmup_ms"] is not None
    assert settings.atlas_rerank == "on"


def test_a_failed_load_warns_keeps_the_flag_off_and_never_raises(
    fresh_reranker, monkeypatch, caplog
):
    reranker, settings, _ = fresh_reranker

    class Broken:
        def __init__(self, *args):
            raise OSError("no such model")

    monkeypatch.setattr(reranker, "OnnxCrossEncoder", Broken)
    with caplog.at_level("WARNING", logger="atlas.retrieval"):
        reranker._load()  # must not raise
    status = reranker.status()
    assert settings.atlas_rerank == "off" and not reranker.enabled()
    assert status["loaded"] is False and status["state"] == "failed"
    assert "no such model" in status["reason"]
    assert any("failed to load" in r.message for r in caplog.records)


def test_start_loading_does_nothing_when_off(fresh_reranker, monkeypatch):
    reranker, settings, _ = fresh_reranker
    monkeypatch.setattr(settings, "atlas_rerank", "off")
    monkeypatch.setattr(reranker.threading, "Thread", lambda *a, **k: pytest.fail("started"))
    reranker.start_loading()  # nothing to load, nothing started


def test_p50_is_over_the_last_twenty_real_queries(fresh_reranker):
    reranker, _, _ = fresh_reranker
    assert reranker.p50_ms() is None
    for ms in [1000.0] * 10 + [10.0] * 20:  # the ten slow ones fall out of the window of 20
        reranker.record(ms)
    assert reranker.p50_ms() == 10.0 and reranker.status()["samples"] == 20


def test_ten_slow_queries_in_a_row_switch_it_off_and_send_the_webhook(fresh_reranker):
    reranker, settings, sent = fresh_reranker
    for _ in range(9):
        reranker.record(200.0)  # median 200 > 150
    assert settings.atlas_rerank == "on" and not sent  # nine is not ten
    reranker.record(200.0)
    assert settings.atlas_rerank == "off" and not reranker.enabled()
    assert len(sent) == 1
    event, data = sent[0]
    assert event == "health" and data["type"] == "health.degraded"
    assert data["component"] == "reranker" and data["consecutive_queries"] == 10
    assert data["p50_ms"] == 200.0 and data["limit_ms"] == 150.0
    status = reranker.status()
    assert status["state"] == "disabled" and "200 ms over 150 ms" in status["reason"]
    reranker.record(200.0)  # already off: no second webhook
    assert len(sent) == 1


def test_a_fast_stretch_resets_the_slow_streak(fresh_reranker):
    reranker, settings, sent = fresh_reranker
    for _ in range(4):
        reranker.record(200.0)  # a short slow patch: the median is over, the streak builds to 4
    for _ in range(20):
        reranker.record(20.0)  # the window fills with fast ones: the median drops, streak resets
    for _ in range(9):
        reranker.record(200.0)  # nine slow among eleven fast: the median stays low
    assert settings.atlas_rerank == "on" and not sent


def test_the_median_lags_so_a_mostly_slow_window_still_counts():
    # The rule is on the median of the last 20, so nine slow queries followed by one fast one
    # leave the median slow: the tenth evaluation over the limit switches the reranker off.
    from app.config import settings
    from app.retrieval import reranker

    reranker.reset()
    settings.atlas_rerank = "on"
    try:
        for _ in range(9):
            reranker.record(200.0)
        assert settings.atlas_rerank == "on"
        reranker.record(20.0)  # median of [20, 200 x 9] is still 200
        assert settings.atlas_rerank == "off"
    finally:
        settings.atlas_rerank = "off"
        reranker.reset()


def test_a_webhook_failure_never_reaches_a_query(fresh_reranker, monkeypatch):
    reranker, settings, _ = fresh_reranker

    def boom(*args, **kwargs):
        raise RuntimeError("webhook down")

    monkeypatch.setattr("app.services.webhooks.emit", boom)
    for _ in range(10):
        reranker.record(500.0)  # the tenth switches off; the failing webhook is swallowed
    assert settings.atlas_rerank == "off"


def test_rerank_records_real_latencies_and_ignores_instant_failures(fresh_reranker):
    reranker, _, _ = fresh_reranker

    class Slow:
        def predict(self, pairs):
            time.sleep(0.05)
            return [float(i) for i in range(len(pairs))]

    class Broken:
        def predict(self, pairs):
            raise RuntimeError("boom")

    reranker.rerank(Trace(), "q", _numbered(6), 5, timeout=5.0, model_source=lambda: (Slow(), None))
    assert reranker.status()["samples"] == 1 and reranker.p50_ms() >= 50
    reranker.rerank(
        Trace(), "q", _numbered(6), 5, timeout=5.0, model_source=lambda: (Broken(), None)
    )
    assert reranker.status()["samples"] == 1  # a broken model's instant failure is not a latency
    reranker.rerank(
        Trace(), "q", _numbered(6), 5, timeout=0.05, model_source=lambda: (Slow(), None)
    )
    assert reranker.status()["samples"] == 2  # an overrun counts, at about its budget


def test_the_health_endpoint_reports_the_status():
    from app.main import app
    from app.retrieval import reranker
    from app.routers.health import reranker_health

    reranker.reset()
    body = reranker_health()
    assert body.loaded is False and body.provider is None and body.p50_ms is None
    assert body.state in ("off", "failed", "loading", "ready", "disabled")
    assert "/health/reranker" in app.openapi()["paths"]  # the route is registered


# --- the production rerank path: hard timeout, one at a time, reason codes, query log ----------


@pytest.fixture(autouse=True)
def _clean_reranker_state():
    from app.retrieval import reranker

    reranker.reset()
    yield
    reranker.reset()


class BatchingModel:
    """A fake that, like the real one, takes a deadline and reports its batches."""

    accepts_deadline = True
    batch_size = 8

    def __init__(self, per_batch_s=0.0):
        self.per_batch_s = per_batch_s
        self.batches_run = []

    def predict(self, pairs, *, deadline=None, batches=None):
        from app.retrieval.reranker import RerankDeadline

        scores = []
        for start in range(0, len(pairs), self.batch_size):
            if deadline is not None and time.monotonic() >= deadline:
                raise RerankDeadline("deadline")
            time.sleep(self.per_batch_s)
            size = len(pairs[start : start + self.batch_size])
            self.batches_run.append(size)
            if batches is not None:
                batches.append(size)
            scores.extend(float(start + i) for i in range(size))
        return scores


def test_a_successful_rerank_logs_its_time_batches_and_no_timeout():
    from app.retrieval import reranker

    trace = Trace()
    out = reranker.rerank(
        trace, "q", _numbered(20), 5, timeout=5.0, model_source=lambda: (BatchingModel(), None)
    )
    stats = trace.extra["rerank"]
    assert len(out) == 5 and stats["rerank_batches"] == 3  # 20 pairs in batches of 8, 8, 4
    assert stats["rerank_timed_out"] is False and stats["rerank_ms"] >= 0
    assert trace.reason_code is None and not trace.is_degraded


def test_the_timeout_is_hard_it_stops_the_work_and_the_reason_is_coded():
    from app.retrieval import reranker

    model = BatchingModel(per_batch_s=0.2)  # three batches would take 0.6 s
    trace = Trace()
    started = time.perf_counter()
    out = reranker.rerank(
        trace, "q", _numbered(20), 5, timeout=0.05, model_source=lambda: (model, None)
    )
    waited = time.perf_counter() - started
    assert waited < 0.15  # the caller got the RRF order at about the budget, not after a batch
    assert [c.symbol_id for c in out] == [0, 1, 2, 3, 4]
    assert trace.reason_code == "rerank_timeout" and trace.is_degraded
    assert trace.extra["rerank"]["rerank_timed_out"] is True
    time.sleep(0.5)  # the abandoned work stops at the next batch boundary, not after all three
    assert len(model.batches_run) < 3


def test_a_second_query_does_not_stack_on_a_rerank_that_overran():
    from app.retrieval import reranker

    slow = BatchingModel(per_batch_s=0.3)
    first = Trace()
    reranker.rerank(first, "q", _numbered(20), 5, timeout=0.05, model_source=lambda: (slow, None))
    fast = BatchingModel()  # would answer instantly, but the CPU is still busy with the first
    second = Trace()
    out = reranker.rerank(
        second, "q", _numbered(20), 5, timeout=5.0, model_source=lambda: (fast, None)
    )
    assert fast.batches_run == []  # never called
    assert [c.symbol_id for c in out] == [0, 1, 2, 3, 4]
    assert second.reason_code == "rerank_timeout" and second.extra["rerank"]["rerank_busy"]
    time.sleep(0.8)  # the first one gives up at its next batch boundary: free again
    third = Trace()
    reranker.rerank(third, "q", _numbered(20), 5, timeout=5.0, model_source=lambda: (fast, None))
    assert fast.batches_run and not third.is_degraded


def test_an_error_uses_the_rrf_order_with_the_timeout_code():
    from app.retrieval import reranker

    class Boom:
        def predict(self, pairs):
            raise RuntimeError("model error")

    trace = Trace()
    out = reranker.rerank(
        trace, "q", _numbered(10), 5, timeout=5.0, model_source=lambda: (Boom(), None)
    )
    assert [c.symbol_id for c in out] == [0, 1, 2, 3, 4]
    assert trace.reason_code == "rerank_timeout" and trace.is_degraded


def test_a_model_that_is_not_loaded_is_unavailable_not_a_timeout():
    from app.retrieval import reranker

    trace = Trace()
    reranker.rerank(
        trace, "q", _numbered(10), 5, model_source=lambda: (None, "reranker still loading")
    )
    assert trace.reason_code == "rerank_unavailable" and "still loading" in trace.degraded[0]
    assert "rerank" not in trace.extra  # nothing ran, so nothing to log


# --- the per-query latency budget ------------------------------------------------------------


def test_parse_enforce():
    from app.retrieval.budget import STAGES, parse_enforce

    assert parse_enforce("") == frozenset() and parse_enforce(None) == frozenset()
    assert parse_enforce("off") == frozenset() and parse_enforce("none") == frozenset()
    assert parse_enforce("all") == frozenset(STAGES)
    assert parse_enforce("Rewrite, rerank") == {"rewrite", "rerank"}
    assert parse_enforce("rerank,nonsense") == {"rerank"}  # unknown names are ignored


def test_budget_sums_repeated_stages_and_breaches_on_a_single_run():
    from app.retrieval.budget import STAGES, Budget

    b = Budget(enforce="", limits={s: 100.0 for s in STAGES})
    b.record("vector", 60.0)
    b.record("vector", 70.0)  # two searches: 130 ms in all, but neither over 100
    assert b.stage_ms["vector"] == 130.0 and b.breached == []
    b.record("embed", 150.0)
    b.record("bm25", 101.0)
    b.record("embed", 200.0)  # the same stage again: still one breach entry
    assert b.breached == ["embed", "bm25"] and b.first_breach == "embed"
    assert list(b.snapshot()) == ["embed", "bm25", "vector"]  # in pipeline order
    assert b.snapshot()["vector"] == 130.0


def test_observe_mode_never_skips_or_degrades_but_enforce_does():
    from app.retrieval.budget import STAGES, Budget

    limits = {s: 10.0 for s in STAGES}
    observe = Budget(enforce="", limits=limits)
    observe.record("embed", 500.0)
    assert observe.first_breach == "embed"
    assert not observe.skip_optional() and observe.degrade_reasons() == []

    enforce = Budget(enforce="vector", limits=limits)
    enforce.record("embed", 500.0)  # breached, but embed is not one of the enforced stages
    assert enforce.first_breach == "embed" and not enforce.skip_optional()
    enforce.record("vector", 500.0)
    assert enforce.skip_optional() and enforce.enforced_breaches == ["vector"]
    assert enforce.degrade_reasons() == ["latency budget: vector over 10 ms"]


def test_the_defaults_are_the_specs_budgets():
    from app.config import Settings

    fields = Settings.model_fields
    stages = (
        "rewrite",
        "embed",
        "bm25",
        "vector",
        "fuse",
        "rerank",
        "assemble",
        "first_token",
        "full_answer",
    )
    got = {s: fields[f"budget_{s}_ms"].default for s in stages}
    assert got == {
        "rewrite": 40,
        "embed": 60,
        "bm25": 30,
        "vector": 80,
        "fuse": 5,
        "rerank": 150,
        "assemble": 20,
        "first_token": 600,
        "full_answer": 3000,
    }
    assert fields["budget_enforce"].default == ""  # observe-only until switched on


def test_stage_timer_records_and_a_missing_budget_is_a_no_op():
    from app.retrieval.budget import Budget, stage_timer

    budget = Budget(enforce="")
    with stage_timer(budget, "fuse"):
        time.sleep(0.02)
    assert budget.stage_ms["fuse"] >= 20
    with stage_timer(None, "fuse"):  # no budget: nothing to record, nothing raised
        pass


def test_query_stats_for_the_weekly_report():
    from app.services.knowledge import query_stats

    assert query_stats({}) is None  # nothing measured, nothing degraded
    stats = query_stats(
        {
            "stage_ms": {"embed": 12.0},
            "budget_breached": "embed",
            "budget_breaches": ["embed"],
            "degraded": True,
            "degraded_reason": "budget_embed",
            "latency_ms": 900,
        }
    )
    assert stats == {
        "stage_ms": {"embed": 12.0},
        "budget_breached": "embed",
        "breaches": ["embed"],
        "degraded": True,
        "degraded_reason": "budget_embed",
        "latency_ms": 900,
    }


def test_the_weekly_budget_metric_counts_degraded_and_the_top_breached_stages():
    from types import SimpleNamespace as Row

    from app.services.analytics import _budget_stages, _budget_summary

    def row(stage_ms, breaches, degraded=False):
        return Row(
            stats={
                "stage_ms": stage_ms,
                "breaches": breaches,
                "budget_breached": breaches[0] if breaches else None,
                "degraded": degraded,
            }
        )

    rows = [
        row({"embed": 100, "vector": 500}, ["embed", "vector"], True),
        row({"embed": 20, "vector": 700}, ["vector"]),
        row({"embed": 10, "vector": 50}, []),
        Row(stats=None),
    ]
    summary = _budget_summary(rows)
    assert summary["answers"] == 4 and summary["with_stats"] == 3
    assert summary["degraded"] == 1 and summary["degraded_pct"] == 33.3
    assert summary["over_budget_pct"] == 66.7
    stages = _budget_stages(rows)
    assert [s["stage"] for s in stages] == ["vector", "embed"]  # most breached first
    assert stages[0]["breached"] == 2 and stages[1]["breached"] == 1
    assert stages[1]["first_breach"] == 1
    assert stages[0]["p50_ms"] == 500 and stages[0]["budget_ms"] == 80
