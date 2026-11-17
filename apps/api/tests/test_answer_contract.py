"""The answer contract: five states, none a refusal, and the refusal sentence never leaves."""

from types import SimpleNamespace

import pytest

from app.assistant import contract
from app.assistant.service import Assistant, Options
from app.schemas import CodeChunk

BANNED = "I don't have that in the knowledge base"


def chunk(score=0.8, file="a/signer.py"):
    return CodeChunk(
        symbol_id=1,
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
    """A model that answers each time it is asked with the next of `replies`."""

    def __init__(self, *replies):
        self.name, self.label, self.models = "gemini", "Gemini", ["g1"]
        self.replies, self.calls = list(replies), []

    def searches(self, model):
        return False

    def stream(self, model, system, turns, outcome, *, web, temperature=None, max_tokens=None):
        self.calls.append(SimpleNamespace(system=system))
        reply = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        outcome.model = model
        for start in range(0, len(reply), 5):  # in small pieces: the phrase arrives split
            yield reply[start : start + 5]


def run(agent, chunks=(), question="How is it unsigned?", **options):
    events = list(Assistant([agent]).respond(question, chunks, (), "auto", Options(**options)))
    streamed = "".join(
        d["text"] for n, d in events if n == "delta"
    )  # everything a client would have shown, were there no reset
    return events, streamed, events[-1][1]


# --- the banned sentence ------------------------------------------------------------------


def test_the_banned_sentence_is_found_however_it_is_written():
    assert contract.find_banned(f"{BANNED}.")
    assert contract.find_banned("i DON’T have that  in the\nknowledge base")  # curly, spacing
    assert contract.find_banned("Sorry. I don't have that in the knowledge base, but...")
    assert not contract.find_banned("The knowledge base does not hold that, but see [a.py:1-2].")
    assert not contract.find_banned(None)


def test_the_guard_holds_back_text_until_it_is_safe_and_catches_a_split_phrase():
    guard = contract.BannedGuard()
    sent = ""
    for piece in ("Well, I don", "'t have th", "at in the know", "ledge base. Sorry."):
        sent += guard.feed(piece)
    sent += guard.flush()
    assert guard.hit
    assert "have that" not in sent and "knowledge base" not in sent  # none of it left

    clean = contract.BannedGuard()
    out = "".join(clean.feed(p) for p in ["It splits ", "the value ", "at the separator."])
    assert out + clean.flush() == "It splits the value at the separator."
    assert not clean.hit


def test_scrub_rewrites_a_draft():
    assert BANNED not in contract.scrub(f"Draft. {BANNED}.")
    assert "no source found" in contract.scrub("i don’t have that in the knowledge base")


# --- the five states ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "state"),
    [
        ({"epistemic": "known", "citations": [{"verified": True}]}, "VERIFIED"),
        ({"epistemic": "known", "citations": [{"verified": False}]}, "INFERRED"),
        ({"epistemic": "inferred"}, "INFERRED"),
        ({"epistemic": "partial"}, "INFERRED"),
        ({"epistemic": "conflicted"}, "INFERRED"),
        ({"epistemic": "web"}, "REPORTED"),
        ({"epistemic": "general"}, "UNVERIFIED"),
        ({"epistemic": "absent"}, "EVIDENCE_GAP"),
        ({"route": "chat"}, None),  # small talk makes no claim
        ({"route": "image"}, None),
        ({"route": "review", "analysis": {"score": 80}}, "VERIFIED"),
    ],
)
def test_the_state_follows_what_the_answer_rests_on(data, state):
    assert contract.derive_state(data) == state


def test_strict_is_never_unverified_or_reported():
    assert contract.derive_state({"epistemic": "general"}, strict=True) == "EVIDENCE_GAP"
    assert contract.derive_state({"epistemic": "web"}, strict=True) == "EVIDENCE_GAP"
    assert (
        contract.derive_state(
            {"epistemic": "known", "citations": [{"verified": True}]}, strict=True
        )
        == "VERIFIED"
    )


def test_a_general_answer_says_it_is_unverified():
    _, _, done = run(Agent("Canberra."), question="What is the capital of Australia?")
    assert done["answer_state"] == "UNVERIFIED"
    assert done["answer"].startswith("**Unverified:**")
    assert done["answer"].endswith("Canberra.")


def test_a_cited_answer_is_verified():
    _, _, done = run(Agent("It splits the value [a/signer.py:10-20]."), [chunk()])
    assert done["answer_state"] == "VERIFIED"
    assert done["answer"] == "It splits the value [a/signer.py:10-20]."  # nothing added


def test_a_web_answer_lists_its_urls_and_its_date():
    data = {
        "epistemic": "web",
        "answer": "Python 3.15 was released.",
        "web_sources": [{"title": "Release notes", "url": "https://python.org/news"}],
    }
    out = contract.apply(
        data,
        strict=False,
        grounded=False,
        web_enabled=True,
        queries=[],
        reranking=None,
        closest=None,
        floor=0.3,
    )
    assert out["answer_state"] == "REPORTED"
    assert "https://python.org/news" in out["answer"] and "as of " in out["answer"]
    assert out["as_of"] and out["as_of"] in out["answer"]


# --- the evidence gap ---------------------------------------------------------------------


def test_strict_with_nothing_found_reports_the_gap_without_asking_a_model():
    agent = Agent("A guess.")
    near = chunk(score=0.12)
    _, _, done = run(agent, [near], strict=True, closest=near, search_queries=("q1", "q2"))
    assert agent.calls == []
    assert done["answer_state"] == "EVIDENCE_GAP" and done["epistemic"] == "absent"
    text = done["answer"]
    assert BANNED not in text
    for part in ("Tools tried", "Closest match", "Next step"):
        assert part in text
    assert "2 queries" in text and "Strict sources only is on" in text
    assert "a/signer.py:10-20" in text and "0.12" in text  # the closest passage, with its score
    gap = done["evidence_gap"]
    assert gap["closest"]["file"] == "a/signer.py" and len(gap["next_steps"]) >= 3
    assert done["citations"] == [] and done["chunks"] == []


def test_a_gap_with_nothing_close_still_says_what_was_tried_and_what_to_do():
    _, _, done = run(Agent("x"), [], about_sources=True)
    assert done["answer_state"] == "EVIDENCE_GAP"
    assert "Nothing in the knowledge base came close." in done["answer"]
    assert "Next step" in done["answer"] and len(done["answer"].splitlines()) > 5


# --- no output carries the sentence --------------------------------------------------------


def test_a_model_that_refuses_is_asked_again_and_the_refusal_never_streams():
    agent = Agent(f"{BANNED}.", "It splits the value [a/signer.py:10-20].")
    events, streamed, done = run(agent, [chunk()])
    assert len(agent.calls) == 2  # regenerated once
    assert "Never write the sentence" in agent.calls[1].system
    assert BANNED not in streamed and BANNED not in done["answer"]
    assert done["answer_state"] == "VERIFIED"
    assert ("reset", {}) in events  # the client drops what came before


def test_a_model_that_keeps_refusing_ends_in_the_evidence_gap_report():
    agent = Agent(f"Sorry. {BANNED}.")
    _events, streamed, done = run(agent, [chunk()], closest=chunk(score=0.2))
    assert len(agent.calls) == 1 + contract.MAX_REGENERATIONS
    assert BANNED not in streamed
    assert not contract.has_banned(done["answer"])
    assert done["answer_state"] == "EVIDENCE_GAP"
    assert "Tools tried" in done["answer"] and "a/signer.py" in done["answer"]


def test_a_refusal_hidden_mid_answer_is_caught_too():
    agent = Agent(
        "It splits the value. Also, " + BANNED + " about the timestamp [a/signer.py:10-20].",
        "It splits the value [a/signer.py:10-20].",
    )
    _, streamed, done = run(agent, [chunk()])
    assert BANNED not in streamed and BANNED not in done["answer"]
    assert len(agent.calls) == 2
