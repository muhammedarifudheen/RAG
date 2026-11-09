"""The evaluation metrics, checked by hand-worked cases (no database, no network)."""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.metrics import (
    Hit,
    Target,
    citation_precision,
    declined,
    matches,
    must_include_coverage,
    percentile,
    score_retrieval,
)
from evals.run_evals import regressions


def test_path_suffix_and_line_overlap():
    hit = Hit("apps/api/app/services/search.py", 10, 20)
    assert matches(hit, Target("search.py"))
    assert matches(hit, Target("app/services/search.py"))
    assert not matches(hit, Target("earch.py"))  # a suffix of the name is not a path
    assert matches(hit, Target("search.py", 15, 30))
    assert not matches(hit, Target("search.py", 21, 30))


def test_ranking_metrics():
    hits = [Hit("a.py", 1, 5), Hit("b.py", 1, 5), Hit("c.py", 1, 5)]
    r = score_retrieval(hits, [Target("b.py"), Target("z.py")], ks=(1, 3))
    assert r.reciprocal_rank == 0.5  # b.py is at rank 2
    assert r.hit_at == {1: 0.0, 3: 1.0}
    assert r.recall_at == {1: 0.0, 3: 0.5}  # one of two targets found
    # one relevant hit at rank 2; the ideal puts both targets at ranks 1-2
    assert math.isclose(r.ndcg_at[3], (1 / math.log2(3)) / (1 + 1 / math.log2(3)))


def test_ndcg_never_exceeds_one_when_a_file_has_many_hits():
    hits = [Hit("a.py", i, i + 1) for i in range(1, 6)]  # five excerpts, all from a.py
    r = score_retrieval(hits, [Target("a.py")], ks=(5,))
    assert r.ndcg_at[5] == 1.0 and r.recall_at[5] == 1.0


def test_three_chunks_from_one_relevant_file_do_not_push_ndcg_above_one():
    hits = [Hit("a.py", 1, 5), Hit("a.py", 10, 15), Hit("a.py", 20, 25)]
    r = score_retrieval(hits, [Target("a.py")], ks=(1, 3, 10))
    for k in (1, 3, 10):
        assert r.ndcg_at[k] == 1.0 and r.ndcg_chunk_at[k] == 1.0  # one file, found at rank 1
        assert r.ndcg_at[k] <= 1.0 and r.ndcg_chunk_at[k] <= 1.0
    # Two relevant files, three chunks of the first then the second: still bounded by 1.
    both = score_retrieval(hits + [Hit("b.py", 1, 2)], [Target("a.py"), Target("b.py")], ks=(10,))
    assert 0 < both.ndcg_at[10] <= 1.0 and 0 < both.ndcg_chunk_at[10] <= 1.0
    assert both.ndcg_at[10] > both.ndcg_chunk_at[10]  # b.py is 2nd file, but the 4th chunk


def test_nothing_found():
    r = score_retrieval([Hit("a.py", 1, 2)], [Target("b.py")], ks=(5,))
    assert r.reciprocal_rank == 0 and r.hit_at[5] == 0 and r.ndcg_at[5] == 0


def test_answer_checks():
    assert must_include_coverage("It uses Reciprocal rank fusion", ["reciprocal", "mmr"]) == 0.5
    assert must_include_coverage("anything", []) == 1.0
    assert declined("I don't have that in the knowledge base.")
    assert declined("Some text.", epistemic="absent")
    assert not declined("I don't have that, but see [a.py:1-2].", citations=1)


def test_citation_precision():
    cites = [
        {"file": "a.py", "start_line": 1, "end_line": 5, "verified": True},
        {"file": "b.py", "start_line": 1, "end_line": 5, "verified": True},  # not a target
        {"file": "a.py", "start_line": 9, "end_line": 9, "verified": False},  # unverified
    ]
    assert citation_precision(cites, [Target("a.py")]) == 1 / 3
    assert citation_precision([], [Target("a.py")]) is None


def test_percentile_and_regressions():
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([], 95) == 0
    baseline = {"hit@5": 0.9, "false_refusal_rate": 0.0, "latency_p95_ms": 100, "questions": 10}
    summary = {"hit@5": 0.8, "false_refusal_rate": 0.2, "latency_p95_ms": 999, "questions": 12}
    found = regressions(summary, baseline, 0.05)
    assert len(found) == 2  # hit@5 fell and refusals rose; timings and counts are not gated
    assert regressions(baseline, baseline, 0.05) == []


def test_ndcg_is_over_files_so_duplicates_do_not_push_a_file_down():
    # a.py's three chunks collapse to one file at its best rank, so c.py (relevant) is the
    # 2nd file for DCG, not the 4th chunk.
    hits = [Hit("a.py", 1, 2), Hit("a.py", 5, 6), Hit("a.py", 9, 9), Hit("c.py", 1, 2)]
    by_files = score_retrieval(hits, [Target("c.py")], ks=(4,))
    assert math.isclose(by_files.ndcg_at[4], 1 / math.log2(3))  # c.py is the 2nd file
    assert math.isclose(by_files.ndcg_chunk_at[4], 1 / math.log2(5))  # but the 4th chunk
    assert by_files.reciprocal_rank == 0.25  # MRR still reads the chunk ranking


def test_file_dedupe_keeps_chunks_of_a_file_pinned_to_lines():
    from evals.metrics import dedupe_by_file

    hits = [Hit("a.py", 1, 5), Hit("a.py", 50, 60), Hit("b.py", 1, 2), Hit("b.py", 3, 4)]
    kept = dedupe_by_file(hits, [Target("a.py", 50, 60)])
    assert [(h.file, h.start) for h in kept] == [("a.py", 1), ("a.py", 50), ("b.py", 1)]


def test_the_reranker_hook_reorders_the_top_candidates_only():
    from evals.rerank import rerank_top

    chunks = [{"file": f"{n}.py", "name": n, "snippet": n} for n in "abcde"]
    seen = {}

    def score(question, passages):
        seen["n"] = len(passages)
        return [0.1, 0.9, 0.5]  # c is middling, b best, a worst

    out = rerank_top("q", chunks, score, top=3)
    assert [c["name"] for c in out] == ["b", "c", "a", "d", "e"]  # d, e untouched, after
    assert seen["n"] == 3
    assert rerank_top("q", chunks[:1], score, top=3) == chunks[:1]  # nothing to reorder


def test_compare_marks_better_and_worse_by_direction():
    from evals.compare import table

    base = {"ndcg@10": 0.8, "mrr": 0.7, "latency_p95_ms": 500, "recall@5": 0.9}
    new = {"ndcg@10": 0.85, "mrr": 0.6, "latency_p95_ms": 1500, "recall@5": 0.9}
    rows = {line.split()[0]: line for line in table(base, new)[1:]}
    assert rows["ndcg@10"].rstrip().endswith("+")  # up is good
    assert rows["mrr"].rstrip().endswith("-")  # down is bad
    assert rows["latency_p95_ms"].rstrip().endswith("-")  # up is bad for latency
    assert not rows["recall@5"].rstrip().endswith(("+", "-"))  # unchanged


def test_golden_set_spellings_are_both_read(tmp_path):
    from evals.run_evals import load_golden

    path = tmp_path / "g.jsonl"
    path.write_text(
        '{"id": "a", "question": "q", "relevant_paths": [{"file": "x.py", "lines": [1, 5]}],'
        ' "expected_state": "PARTIAL"}\n'
        '{"id": "b", "question": "q", "relevant_paths": [], "expected_state": "REFUSED"}\n'
        '{"id": "c", "question": "q", "relevant": ["y.py"], "answerable": false}\n',
        encoding="utf-8",
    )
    a, b, c = load_golden(path)
    assert a["relevant"][0]["file"] == "x.py" and a["answerable"] is True
    assert b["relevant"] == [] and b["answerable"] is False
    assert c["relevant"] == ["y.py"] and c["answerable"] is False  # the old spelling stands


def test_the_shipped_golden_set_is_well_formed():
    import json
    from pathlib import Path

    from evals.metrics import Target

    path = Path(__file__).resolve().parents[1] / "evals" / "golden" / "golden_set.jsonl"
    items = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    assert len(items) == 40 and len({i["id"] for i in items}) == 40
    states = {"KNOWN", "INFERRED", "PARTIAL", "ABSENT", "CONFLICTED", "REFUSED"}
    for i in items:
        assert i["expected_state"] in states and i["question"] and i["rationale"]
        for target in i["relevant_paths"]:
            Target.parse(target)  # a path, or {"file", "lines"}: never a chunk id
        if i["expected_state"] in ("ABSENT", "REFUSED"):
            assert i["relevant_paths"] == []
        else:
            assert i["relevant_paths"], i["id"]


def test_golden_validation_checks_that_need_no_network():
    from evals.validate_golden import check_distribution, check_states, resolve

    ok = [
        {"id": f"x{i}", "category": "fail-partial", "expected_state": "PARTIAL"} for i in range(20)
    ]
    ok += [{"id": f"m{i}", "category": "multi-hop", "expected_state": "KNOWN"} for i in range(10)]
    ok += [{"id": f"t{i}", "category": "code-trace", "expected_state": "KNOWN"} for i in range(5)]
    ok += [
        {"id": f"v{i}", "category": "adversarial", "expected_state": "REFUSED"} for i in range(5)
    ]
    assert check_distribution(ok).passed and check_states(ok).passed
    assert not check_distribution(ok[:-1]).passed  # 4 adversarial, not 5
    bad = [*ok, {"id": "z", "category": "multi-hop", "expected_state": "MAYBE"}]
    assert not check_states(bad).passed
    known = {"pallets/itsdangerous/src/itsdangerous/signer.py", "wikipedia/en/HMAC"}
    assert resolve("itsdangerous/signer.py", known) == [
        "pallets/itsdangerous/src/itsdangerous/signer.py"
    ]
    assert resolve("signer.p", known) == []  # a suffix of the name is not a path


def _bench_args(**over):
    import argparse

    base = {
        "api": "http://x",
        "token": None,
        "timeout": 5,
        "rerank_top": 20,
        "warmup": 2,
        "budget_ms": 150.0,
        "fallback_on_timeout": None,
        "reranker_fn": lambda question, passages: [float(i) for i in range(len(passages))],
    }
    return argparse.Namespace(**{**base, **over})


def _raw(chunks):
    return {"id": "q", "question": "q", "error": None, "ms": 100.0, "chunks": chunks}


def test_parse_ms_reads_units():
    from evals.run_evals import parse_ms

    assert parse_ms("150ms") == 150.0 and parse_ms("150") == 150.0 and parse_ms("0.15s") == 150.0


def test_rerank_pass_times_warms_up_and_falls_back_on_timeout(monkeypatch):
    import evals.run_evals as run

    calls = []
    monkeypatch.setattr(
        run,
        "call",
        lambda url, **kw: (
            calls.append(url) or {"results": [{"file": "w.py", "name": "w", "snippet": "w"}] * 3}
        ),
    )
    chunks = [{"file": f"{n}.py", "name": n, "snippet": n} for n in "abc"]  # scores 0,1,2: reversed

    within = _raw(list(chunks))
    run.rerank_pass([within], _bench_args(budget_ms=1e9))
    assert [c["name"] for c in within["chunks"]] == ["c", "b", "a"]  # reranked
    assert within["timed_out"] is False and within["degraded"] is False
    assert len(calls) == 2  # two warm-up searches, not timed
    assert within["ms"] > 100.0 and within["rerank_ms"] >= 0  # total = search + rerank

    over = _raw(list(chunks))
    run.rerank_pass([over], _bench_args(fallback_on_timeout=-1.0))  # always over the budget
    assert [c["name"] for c in over["chunks"]] == ["a", "b", "c"]  # the search order kept
    assert over["timed_out"] and over["degraded"]
    assert [c["name"] for c in over["chunks_reranked"]] == ["c", "b", "a"]  # kept to score both


def test_paired_difference_counts_and_interval():
    from evals.ab_repeat import paired, verdict

    a = {f"q{i}": [0.5, 0.5, 0.5] for i in range(10)}
    b = {f"q{i}": [0.6, 0.6, 0.6] for i in range(10)}  # every question 0.1 better, every round
    r = paired(a, b)
    assert r["n"] == 10 and abs(r["mean"] - 0.1) < 1e-9
    assert r["better"] == 10 and r["worse"] == 0 and r["tied"] == 0
    assert r["ci95"][0] > 0.09 and r["ci95"][1] < 0.11
    assert verdict({**r, "noise_sd": 0.02}, 0.02) == "weighted better"
    assert verdict(r, 0.5) == "within noise"  # a gap smaller than the noise is not believed


def test_paired_ignores_missing_values_and_flags_a_loss():
    from evals.ab_repeat import paired, verdict

    a = {"x": [1.0, None, 1.0], "y": [None, None, None], "z": [0.8, 0.8, 0.8]}
    b = {"x": [0.0, 1.0, 0.0], "y": [1.0, 1.0, 1.0], "z": [0.6, 0.6, 0.6]}
    r = paired(a, b)
    assert r["n"] == 2  # y has no round where both arms have a value
    assert r["worse"] == 2 and r["better"] == 0
    assert verdict(r, 0.0) == "weighted worse"
    assert paired({}, {})["n"] == 0 and verdict(paired({}, {}), 0) == "no data"


def test_a_noisy_difference_straddling_zero_is_within_noise():
    from evals.ab_repeat import paired, verdict

    a = {f"q{i}": [0.5] for i in range(8)}
    b = {f"q{i}": [0.5 + (0.3 if i % 2 else -0.3)] for i in range(8)}
    r = paired(a, b)
    assert r["better"] == 4 and r["worse"] == 4
    assert verdict(r, 0.0) == "within noise"
