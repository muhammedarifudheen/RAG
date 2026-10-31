"""Epistemic states: known, inferred, partial, absent or conflicted, never blurred."""

from types import SimpleNamespace

from app.assistant.service import Assistant, Options
from app.schemas import CodeChunk


def chunk():
    return CodeChunk(
        symbol_id=1,
        name="Signer.unsign",
        kind="method",
        file="a/signer.py",
        language="python",
        start_line=10,
        end_line=20,
        signature=None,
        score=0.8,
        snippet="def unsign(self, value):\n    return value",
        snippet_end_line=20,
        truncated=False,
        citation="[a/signer.py:10-20]",
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
        # In pieces, so the state line arrives split.
        for start in range(0, len(self.reply), 7):
            yield self.reply[start : start + 7]


def ask(agent, chunks, **options):
    return list(
        Assistant([agent]).respond("How is it unsigned?", chunks, (), "auto", Options(**options))
    )


def test_a_sources_answer_declares_its_state_which_is_shown_not_written():
    agent = Agent(
        "STATE: PARTIAL\nIt splits the value at the separator [a/signer.py:10-20]. "
        "Missing: how the timestamp is checked."
    )
    events = ask(agent, [chunk()])
    assert "Before answering, classify your epistemic state:" in agent.calls[0].system
    streamed = "".join(data["text"] for name, data in events if name == "delta")
    assert "STATE" not in streamed and streamed.startswith("It splits")
    done = events[-1][1]
    assert done["epistemic"] == "partial"
    assert done["answer"].startswith("It splits")
    assert done["citations"][0]["verified"] is True
    assert done["confidence"]["level"] != "high"  # a partial answer is never rated high


def test_without_a_declared_state_its_citations_decide():
    done = ask(Agent("It splits the value [a/signer.py:10-20]."), [chunk()])[-1][1]
    assert done["epistemic"] == "known"


def test_a_question_about_the_sources_with_nothing_found_is_absent_without_a_model():
    agent = Agent("verify_token_v2 checks a v2 token and returns its payload.")
    events = ask(agent, [], about_sources=True)
    assert agent.calls == []  # never answered from memory
    done = events[-1][1]
    assert done["epistemic"] == "absent"
    assert done["answer"] == "I don't have that in the knowledge base."


def test_other_questions_say_they_come_from_general_knowledge():
    agent = Agent("Canberra.")
    done = list(
        Assistant([agent]).respond("What is the capital of Australia?", [], (), "auto", Options())
    )[-1][1]
    assert done["epistemic"] == "general"
    assert "classify your epistemic state" not in agent.calls[0].system


def test_questions_naming_the_sources_or_their_code_are_about_them(db):
    from app.services.catalog import mentions_sources

    assert mentions_sources(db, "What does format_name return?")
    assert mentions_sources(db, "In acme/pkg, what does verify_token_v2 do?")  # the repo's name
    assert not mentions_sources(db, "What is the capital of Australia?")
    assert not mentions_sources(db, "What does compute_tax_v9 do?")  # no such code
