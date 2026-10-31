"""Atlas's modes, routed by intent: ASK, EXPLORE, COMPARE, BUILD, AUDIT, AGENT, TEACH."""

import time
from types import SimpleNamespace

import pytest

from app.assistant.modes import classify_mode
from app.assistant.service import Assistant, Options
from app.schemas import CodeChunk


@pytest.mark.parametrize(
    ("question", "mode"),
    [
        ("Why does this fail?\n```python\nsign(b'x')\n```", "BUILD"),
        ("Compare Signer and TimestampSigner", "COMPARE"),
        ("HMAC vs a plain hash: which is safer?", "COMPARE"),
        ("How does TimestampSigner work?", "TEACH"),
        ("Audit the knowledge base for stale sources", "AUDIT"),
        ("What gaps does the knowledge base have?", "AUDIT"),
        ("Who calls verify_signature?", "EXPLORE"),
        ("Trace a request from the router to the database layer end to end", "AGENT"),
        ("What is HMAC?", "ASK"),
        ("hello", "ASK"),
    ],
)
def test_the_router_follows_the_users_rules(question, mode):
    assert classify_mode(question) == mode


def chunk():
    return CodeChunk(
        symbol_id=1, name="Signer.unsign", kind="method", file="a/signer.py", language="python",
        start_line=10, end_line=20, signature=None, score=0.8, snippet="def unsign(self): ...",
        snippet_end_line=20, truncated=False, citation="[a/signer.py:10-20]",
    )  # fmt: skip


class Agent:
    def __init__(self, reply="It splits [a/signer.py:10-20]."):
        self.name, self.label, self.models = "gemini", "Gemini", ["g1"]
        self.reply, self.calls = reply, []

    def searches(self, model):
        return False

    def stream(self, model, system, turns, outcome, *, web, temperature=None, max_tokens=None):
        self.calls.append(SimpleNamespace(system=system, content=turns[-1].content))
        outcome.model = model
        yield self.reply


@pytest.mark.parametrize(
    ("mode", "rule"),
    [("COMPARE", "This is a COMPARE question."), ("TEACH", "### One line")],
)
def test_compare_and_teach_get_their_instructions(mode, rule):
    agent = Agent()
    list(Assistant([agent]).respond("q", [chunk()], (), "auto", Options(mode=mode)))
    assert rule in agent.calls[0].system


def test_build_answers_with_the_code_aware_prompt():
    agent = Agent()
    list(Assistant([agent]).respond("why?", [chunk()], (), "auto", Options(mode="BUILD")))
    assert agent.calls[0].content.startswith("You are a codebase assistant.")


def test_every_answer_ends_with_its_footer():
    started = time.monotonic() - 0.25
    done = list(Assistant([Agent()]).respond("q", [chunk()], (), "auto", Options(started=started)))[
        -1
    ][1]
    assert done["mode"] == "ASK" and done["latency_ms"] >= 250
    assert done["footer"].startswith("[confidence: KNOWN] [sources: 1] [latency: ")
    assert done["footer"].endswith("ms]")


def test_explore_and_audit_answer_from_the_database(client):
    explored = client.post(
        "/ask", json={"question": "Who calls format_name?", "style": "concise"}
    ).json()
    assert explored["mode"] == "EXPLORE"
    assert "format_name" in explored["answer"] and "Used by" in explored["answer"]
    assert explored["footer"].startswith("[confidence: ")
    audited = client.post(
        "/ask", json={"question": "Audit the knowledge base coverage", "style": "concise"}
    ).json()
    assert audited["mode"] == "AUDIT"
    assert audited["answer"].startswith("**Knowledge health**")
