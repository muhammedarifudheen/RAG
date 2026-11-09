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
