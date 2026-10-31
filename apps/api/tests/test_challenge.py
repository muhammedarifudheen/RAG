"""The self-challenge: the strongest objection from the retrieved context, then revise or keep."""

from types import SimpleNamespace

from app.assistant.challenge import parse_challenge
from app.assistant.service import Assistant, Options
from app.schemas import CodeChunk

ANSWER = "It compares the signatures with == [a/signer.py:10-20]."
VALID = """OBJECTION: The excerpt shows hmac.compare_digest, not ==, so the answer misstates \
how the comparison is made.
DECISION: VALID
FINAL ANSWER:
It compares the signatures in constant time with hmac.compare_digest [a/signer.py:10-20]."""
INVALID = """**Objection:** The excerpt might not cover every signer.
**Decision:** INVALID
**Reason:** The question is about Signer only, which the excerpt covers.
**Final answer:**
It compares the signatures with == [a/signer.py:10-20]."""


def chunk():
    return CodeChunk(
        symbol_id=1,
        name="Signer.verify_signature",
        kind="method",
        file="a/signer.py",
        language="python",
        start_line=10,
        end_line=20,
        signature=None,
        score=0.8,
        snippet="def verify_signature(self, value, sig):\n    return hmac.compare_digest(a, b)",
        snippet_end_line=20,
        truncated=False,
        citation="[a/signer.py:10-20]",
    )


class Agent:
    def __init__(self, reply):
        self.name, self.label, self.models = "nvidia", "NVIDIA", ["n1"]
        self.reply, self.calls = reply, []

    def searches(self, model):
        return False

    def stream(self, model, system, turns, outcome, *, web, temperature=None, max_tokens=None):
        self.calls.append(SimpleNamespace(content=turns[-1].content))
        outcome.model = model
        yield self.reply


def test_the_reply_is_read_part_by_part():
    valid = parse_challenge(VALID, ANSWER)
    assert valid.valid and valid.final_answer.startswith("It compares the signatures in constant")
    invalid = parse_challenge(INVALID, ANSWER)
    assert not invalid.valid and invalid.final_answer == ANSWER
    assert invalid.reason == "The question is about Signer only, which the excerpt covers."
    assert parse_challenge("The answer looks fine to me.", ANSWER) is None


def test_a_valid_objection_revises_the_answer_and_keeps_the_original():
    agent = Agent(VALID)
    final, report = Assistant([agent]).challenge("How are signatures compared?", ANSWER, [chunk()])
    assert "compare_digest" in final
    assert report.valid and report.original_answer == ANSWER
    assert report.challenged_by == "NVIDIA · n1"
    sent = agent.calls[0].content
    assert "Before you finalize, generate the strongest possible objection" in sent
    assert "[a/signer.py:10-20]\n10| def verify_signature" in sent


def test_an_invalid_objection_keeps_the_answer_with_its_reason():
    final, report = Assistant([Agent(INVALID)]).challenge("q", ANSWER, [chunk()])
    assert final == ANSWER
    assert not report.valid and report.original_answer is None
    assert report.reason.startswith("The question is about Signer only")


def test_answers_from_the_sources_are_marked_to_be_challenged():
    sourced = Agent("It compares in constant time [a/signer.py:10-20].")
    done = list(Assistant([sourced]).respond("How?", [chunk()], (), "auto", Options()))[-1][1]
    assert done["challenge_pending"] is True
    general = Agent("Canberra.")
    done = list(Assistant([general]).respond("Capital of Australia?", [], (), "auto", Options()))
    assert done[-1][1]["challenge_pending"] is False


def test_any_answer_can_be_challenged_through_ask(plain_client):
    from app.assistant import get_assistant
    from app.db import get_db
    from app.embedding import get_embedder
    from app.main import app

    app.dependency_overrides[get_assistant] = lambda: Assistant([Agent(VALID)])
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_embedder] = lambda: None
    try:
        body = plain_client.post(
            "/ask",
            json={
                "question": "How are signatures compared?",
                "task": "challenge",
                "answer": ANSWER,
                "chunks": [chunk().model_dump()],
            },
        ).json()
    finally:
        for dependency in (get_assistant, get_db, get_embedder):
            app.dependency_overrides.pop(dependency, None)
    assert body["challenge"]["valid"] is True
    assert "compare_digest" in body["answer"]
    assert body["citations"][0]["verified"] is True
