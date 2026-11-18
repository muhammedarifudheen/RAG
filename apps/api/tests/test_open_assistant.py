"""Atlas answers every kind of question: the public image is not grounded, a general question
gets a real answer, and when nothing is found the reply is friendly and still says what to do."""

import re
from pathlib import Path
from types import SimpleNamespace

from app.assistant import contract
from app.assistant.service import Assistant, Options

REPO = Path(__file__).resolve().parents[3]


def test_the_public_server_image_is_not_grounded():
    """ASSISTANT_GROUNDED=true made the server refuse everything outside its sources."""
    dockerfile = (REPO / "deploy" / "server" / "Dockerfile").read_text(encoding="utf-8")
    setting = re.search(r"ASSISTANT_GROUNDED=(\w+)", dockerfile)
    assert setting and setting.group(1).lower() == "false"


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


def ask(agent, question, **options):
    events = list(Assistant([agent]).respond(question, [], (), "auto", Options(**options)))
    return events[-1][1]


def test_a_question_outside_the_sources_is_answered_not_refused():
    agent = Agent("The Rust borrow checker enforces ownership rules at compile time.")
    done = ask(agent, "What does the Rust borrow checker do?")
    assert agent.calls, "the model was asked"
    assert done["answer_state"] == "UNVERIFIED"  # honest about where it comes from...
    assert "borrow checker enforces ownership" in done["answer"]  # ...and actually answers
    assert done["answer"].startswith("**Unverified:**")
    assert "worth double-checking" in done["answer"].lower() or "double-checking" in done["answer"]


def test_a_greeting_is_plain_friendly_chat_with_no_label():
    done = ask(Agent("Hello! How can I help today?"), "hi")
    assert done.get("answer_state") is None
    assert done["answer"] == "Hello! How can I help today?"


def test_when_nothing_is_found_the_reply_is_friendly_and_still_useful():
    text, _ = contract.evidence_gap(
        tools=["Knowledge base: 4 queries."],
        closest=None,
        steps=contract.next_steps(closest=None, strict=False, grounded=False),
        floor=0.3,
    )
    assert text.startswith("I couldn't find this in your sources")
    assert "Evidence gap" not in text  # no clinical label in the reply itself
    for part in ("Tools tried", "Closest match", "Next step"):
        assert part in text
