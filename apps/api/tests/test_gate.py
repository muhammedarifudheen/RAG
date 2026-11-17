"""The relevance gate and the low-confidence path: weak excerpts are given, labelled, not dropped."""

from types import SimpleNamespace

from app.assistant.service import Assistant, Options
from app.retrieval import gate
from app.schemas import CodeChunk


def chunk(symbol_id=1, score=0.8, file="a/signer.py"):
    return CodeChunk(
        symbol_id=symbol_id,
        name="Signer.unsign",
        kind="method",
        file=file,
        language="python",
        start_line=10,
        end_line=20,
        signature=None,
        score=score,
        snippet="def unsign(self, value):\n    return value",
        snippet_end_line=20,
        truncated=False,
        citation=f"[{file}:10-20]",
    )


class Agent:
    def __init__(self, reply):
        self.name, self.label, self.models = "gemini", "Gemini", ["g1"]
        self.reply, self.calls = reply, []

    def searches(self, model):
        return False

    def stream(self, model, system, turns, outcome, *, web, temperature=None, max_tokens=None):
        self.calls.append(SimpleNamespace(system=system, turns=turns))
        outcome.model = model
        yield self.reply


def run(agent, chunks, **options):
    events = list(Assistant([agent]).respond("How is it unsigned?", chunks, (), "auto", Options(**options)))
    return events[-1][1]


# --- the pure parts -----------------------------------------------------------------------


def test_summarise_gives_the_best_scores():
    verdicts = {1: (7, "close"), 2: (3, ""), 3: (9, "exact")}
    top, similarity, scores = gate.summarise(verdicts, [chunk(1, 0.4), chunk(2, 0.9), chunk(3, 0.5)])
    assert top == 9 and similarity == 0.9 and scores == [9, 7, 3]
    assert gate.summarise({}, []) == (None, None, [])


def test_low_means_the_best_score_is_under_the_gate_and_nothing_judged_is_not_low():
    assert gate.is_low(3, 4) and not gate.is_low(4, 4) and not gate.is_low(9, 4)
    assert not gate.is_low(None, 4)  # a judge that was down says nothing about the excerpts


def test_the_pick_is_the_best_three_by_judge_then_similarity_with_scores_set():
    candidates = [chunk(i, score=s) for i, s in enumerate((0.5, 0.6, 0.7, 0.4, 0.3), 1)]
    verdicts = {1: (3, "a"), 2: (3, "b"), 3: (2, "c"), 4: (3, "d"), 5: (0, "e")}
    picked = gate.low_confidence_pick(candidates, verdicts)
    assert [c.symbol_id for c in picked] == [2, 1, 4]  # three 3s, nearest first
    assert [c.relevance for c in picked] == [3, 3, 3]
    assert picked[0].relevance_reason == "b"


def test_the_pick_works_when_the_judge_scored_nothing():
    picked = gate.low_confidence_pick([chunk(1, 0.2), chunk(2, 0.6)], {})
    assert [c.symbol_id for c in picked] == [2, 1]


def test_percentile():
    assert gate.percentile([], 20) == 0
    assert gate.percentile([5], 20) == 5
    assert gate.percentile([10, 9, 8, 7, 6], 20) == 6.8  # 20% of the way from 6 to 7... (4 gaps)


# --- through the assistant ------------------------------------------------------------------


def test_weak_excerpts_are_dropped_by_the_floor_without_the_path():
    agent = Agent("x")
    done = run(agent, [chunk(score=0.1)], strict=True, closest=chunk(score=0.1))
    assert agent.calls == []  # nothing reached the model: the evidence-gap report
    assert done["answer_state"] == "EVIDENCE_GAP" and done["low_confidence"] is False


def test_with_the_path_weak_excerpts_reach_the_model_labelled():
    agent = Agent("It splits the value [a/signer.py:10-20]. The match is weak.")
    done = run(agent, [chunk(score=0.1)], strict=True, low_confidence=True)
    assert len(agent.calls) == 1  # asked, not refused
    sent = agent.calls[0].turns[-1].content
    assert "<low_confidence>" in sent and "a/signer.py" in sent
    assert done["low_confidence"] is True
    assert done["answer_state"] == "INFERRED"  # weak evidence is never VERIFIED
    assert done["chunks"] and done["citations"][0]["verified"] is True


def test_at_most_three_weak_excerpts_are_given():
    agent = Agent("It splits [a/signer.py:10-20].")
    run(agent, [chunk(i, 0.1) for i in range(1, 7)], strict=True, low_confidence=True)
    assert agent.calls[0].turns[-1].content.count("[a/signer.py:10-20]\n") <= 3


def test_a_model_that_finds_the_weak_excerpts_useless_ends_in_the_gap_report():
    agent = Agent("STATE: ABSENT\n")
    done = run(agent, [chunk(score=0.1)], strict=True, low_confidence=True, closest=chunk(score=0.1))
    assert done["answer_state"] == "EVIDENCE_GAP"
    assert "Closest match" in done["answer"] and "I don't have that" not in done["answer"]
