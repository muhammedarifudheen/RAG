"""The uncertainty budget: 3 units; over it, the answer is withheld."""

from types import SimpleNamespace

from app.assistant.service import Assistant, Options
from app.assistant.uncertainty import take_tag
from app.schemas import CodeChunk


def chunk(file="a/signer.py", weight=3, symbol_id=1):
    return CodeChunk(
        symbol_id=symbol_id,
        name="unsign",
        kind="method",
        file=file,
        language="python",
        start_line=10,
        end_line=20,
        signature=None,
        score=0.8,
        snippet="def unsign(self):\n    pass",
        snippet_end_line=20,
        truncated=False,
        citation=f"[{file}:10-20]",
        weight=weight,
    )


class Agent:
    def __init__(self, reply):
        self.name, self.label, self.models = "gemini", "Gemini", ["g1"]
        self.reply, self.calls = reply, []

    def searches(self, model):
        return False

    def stream(self, model, system, turns, outcome, *, web, temperature=None, max_tokens=None):
        self.calls.append(SimpleNamespace(system=system))
        outcome.model = model
        yield self.reply


def answer(reply, chunks):
    agent = Agent(reply)
    done = list(Assistant([agent]).respond("How?", chunks, (), "auto", Options()))[-1][1]
    return agent, done


def test_the_tag_is_read_and_taken_off():
    assert take_tag("It splits.\n\n[uncertainty spent: 2/3]") == (2, "It splits.")
    assert take_tag("No tag here.") == (None, "No tag here.")


def test_the_budget_is_the_higher_of_the_models_count_and_what_the_server_sees():
    agent, done = answer(
        "It splits [a/signer.py:10-20].\n[uncertainty spent: 0/3]", [chunk(), chunk("b.py", 3, 2)]
    )
    assert "You have a fixed uncertainty budget of 3." in agent.calls[0].system
    budget = done["uncertainty"]
    assert budget["model"] == 0
    assert budget["reasons"] == ["a single source"]  # only one file was cited
    assert budget["spent"] == 1 and not budget["exceeded"]
    assert "uncertainty spent" not in done["answer"]


def test_over_budget_the_answer_is_withheld_and_not_challenged():
    _, done = answer(
        "STATE: INFERRED\nBased on it, this implies a split [wiki/HMAC:10-20].\n"
        "[uncertainty spent: 4/3]",
        [chunk("wiki/HMAC", 2)],
    )
    assert done["uncertainty"]["exceeded"] is True
    assert done["answer"].startswith(
        "Confidence too low to answer safely. Here's what I found and what's missing:"
    )
    assert done["challenge_pending"] is False
    assert done["confidence"]["level"] == "low"


def test_the_models_own_refusal_counts_as_over_budget():
    _, done = answer(
        "Confidence too low to answer safely. Here's what I found and what's missing: "
        "only a note [a/signer.py:10-20].",
        [chunk()],
    )
    assert done["uncertainty"]["exceeded"] is True
    assert done["answer"].count("Confidence too low") == 1
