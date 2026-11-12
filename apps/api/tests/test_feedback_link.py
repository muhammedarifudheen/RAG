"""The thumbs, linked to the served and shadow chunk orders; no database needed."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.routers import search as search_router
from app.routers.analytics import Feedback
from app.schemas import CodeChunk
from app.services.analytics import MIN_RATED_PER_GROUP, shadow_report


def chunk(i: int, score: float = 0.5) -> CodeChunk:
    return CodeChunk(
        symbol_id=i, name=f"n{i}", kind="function", signature=None, file=f"f{i}.py",
        language="python", start_line=1, end_line=2, score=score, snippet="x",
        snippet_end_line=2, truncated=False, citation=f"[f{i}.py:1-2]",
    )  # fmt: skip


def row(differs: bool, rating: int) -> SimpleNamespace:
    return SimpleNamespace(ranking={"differs": differs}, feedback=rating)


def test_a_vote_must_name_something():
    Feedback(rating="down", answer_hash="abc")
    Feedback(rating="up", question="q")  # the original contract still works
    with pytest.raises(ValidationError):
        Feedback(rating="up")


def test_shadow_rank_keeps_both_orders_and_times_itself():
    chunks = [chunk(1, 0.9), chunk(2, 0.8), chunk(3, 0.7)]
    out = search_router._shadow_rank("what", chunks, chunks)
    assert out["legacy_chosen"] == [1, 2, 3]
    assert sorted(out["shadow_chosen"]) == [1, 2, 3]
    assert out["differs"] == (out["shadow_chosen"] != [1, 2, 3])
    assert out["shadow_score_ms"] < 5


def test_a_shadow_scoring_failure_is_logged_apart_and_never_raised(monkeypatch, caplog):
    def broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(search_router.scoring, "rank", broken)
    with caplog.at_level("ERROR"):
        assert search_router._shadow_rank("q", [chunk(1)], [chunk(1)]) is None
    assert any("shadow_score_errors" in r.getMessage() for r in caplog.records)


def test_a_small_sample_is_not_read():
    report = shadow_report([row(True, -1)] * 3 + [row(False, 1)] * 5)
    assert report["summary"]["enough_to_read"] is False
    assert "Too few" in report["summary"]["reading"]
    assert "Do not draw a conclusion" in report["summary"]["reading"]


def test_a_clear_gap_is_reported_with_its_interval():
    n = MIN_RATED_PER_GROUP * 3
    rows = (
        [row(True, -1)] * (n * 6 // 10)
        + [row(True, 1)] * (n * 4 // 10)
        + [row(False, -1)] * (n // 10)
        + [row(False, 1)] * (n * 9 // 10)
    )
    report = shadow_report(rows)
    assert report["summary"]["enough_to_read"] is True
    delta = report["rows"][2]
    assert delta["down_rate"] > 0.4 and delta["ci95"][0] > 0
    assert "more common where the orders differ" in report["summary"]["reading"]


def test_no_gap_with_enough_votes_says_so():
    n = MIN_RATED_PER_GROUP
    rows = [row(True, -1)] * (n // 3) + [row(True, 1)] * (n - n // 3)
    rows += [row(False, -1)] * (n // 3) + [row(False, 1)] * (n - n // 3)
    report = shadow_report(rows)
    assert report["summary"]["enough_to_read"] is True
    assert "No difference" in report["summary"]["reading"]


def test_unrated_and_unscored_answers_are_left_out():
    rows = [
        SimpleNamespace(ranking=None, feedback=-1),
        SimpleNamespace(ranking={"differs": True}, feedback=None),
    ]
    assert shadow_report(rows)["summary"]["rated"] == 0
