"""The fact-checker: strict answers are checked against their sources, others on request."""

import json
import time
from types import SimpleNamespace

from app.assistant import service as service_module
from app.assistant.factcheck import parse_fact_check
from app.assistant.prompt import fact_check_prompt
from app.assistant.service import Assistant, Options
from app.schemas import CodeChunk

REPORT = {
    "faithful": False,
    "unsupported": ["It uses SHA-512."],
    "citation_errors": ["[signer.py:900-910] is not in the context"],
    "verdict": "One claim is unsupported and one citation is wrong.",
}


def chunk():
    return CodeChunk(
        symbol_id=7,
        name="verify_signature",
        kind="method",
        file="itsdangerous/signer.py",
        language="python",
        start_line=227,
        end_line=240,
        signature="def verify_signature(self, value, sig)",
        score=0.8,
        snippet="def verify_signature(self, value, sig):\n    return hmac.compare_digest(a, b)",
        snippet_end_line=228,
        truncated=False,
        citation="[itsdangerous/signer.py:227-228]",
    )


class Agent:
    """Answers questions with `answer`; fact-checks with `report` (after `delay` seconds)."""

    def __init__(self, name, answer, report, delay=0.0):
        self.name, self.label = name, name.title()
        self.models = [f"{name}-1"]
        self.answer, self.report, self.delay = answer, report, delay
        self.calls = []

    def searches(self, model):
        return False

    def stream(self, model, system, turns, outcome, *, web, temperature=None, max_tokens=None):
        self.calls.append(SimpleNamespace(system=system, content=turns[-1].content))
        outcome.model = model
        if turns[-1].content.startswith("You are a fact-checker."):
            time.sleep(self.delay)
            yield self.report
            return
        yield self.answer


def test_the_checkers_prompt_is_the_users_with_the_answer_and_context_filled_in():
    prompt = fact_check_prompt(
        "How is it checked?", "With {context} [a.py:1-2].", "[a.py:1-2]\n1| x"
    )
    assert prompt.startswith("You are a fact-checker.\n\nQuestion: How is it checked?\n")
    assert "Answer: With {context} [a.py:1-2].\nContext: [a.py:1-2]\n1| x\n" in prompt
    assert prompt.endswith('"citation_errors": [...], "verdict": "<one line>"}')


def test_the_checkers_reply_is_read():
    check = parse_fact_check(f"Here:\n```json\n{json.dumps(REPORT)}\n```")
    assert check.faithful is False
    assert check.unsupported == ["It uses SHA-512."]
    assert check.citation_errors == ["[signer.py:900-910] is not in the context"]
    assert check.verdict.startswith("One claim")
    # "faithful" with problems listed is not faithful.
    assert not parse_fact_check('{"faithful": true, "unsupported": ["x"]}').faithful
    assert parse_fact_check('{"faithful": "true", "verdict": "ok"}').faithful
    assert parse_fact_check("Looks fine to me.") is None


def test_a_strict_answer_is_marked_for_checking_and_not_held_back():
    gemini = Agent("gemini", "It compares [itsdangerous/signer.py:227-228].", json.dumps(REPORT))
    events = list(
        Assistant([gemini]).respond(
            "How is it checked?", [chunk()], (), "auto", Options(strict=True)
        )
    )
    assert events[-1][1]["fact_check_pending"] is True
    assert len(gemini.calls) == 1  # the answer only: the page asks for the check


def test_other_answers_and_not_in_the_sources_are_not_marked():
    gemini = Agent("gemini", "An answer.", json.dumps(REPORT))
    plain = list(Assistant([gemini]).respond("q", [chunk()], (), "auto", Options()))
    assert plain[-1][1]["fact_check_pending"] is False
    nothing = list(
        Assistant([gemini], min_score=0.9).respond("q", [chunk()], (), "auto", Options(strict=True))
    )
    assert nothing[-1][1]["fact_check_pending"] is False


def test_the_check_reads_the_answer_against_its_context():
    gemini = Agent("gemini", "unused", json.dumps(REPORT))
    report = Assistant([gemini]).fact_check(
        "How is it checked?",
        "It compares in constant time [itsdangerous/signer.py:227-228].",
        [chunk()],
    )
    assert report.faithful is False and report.checked_by == "Gemini · gemini-1"
    checked = gemini.calls[-1].content
    assert "Answer: It compares in constant time" in checked
    assert "Context: [itsdangerous/signer.py:227-228]\n227| def verify_signature" in checked


def test_two_checkers_race_and_a_slow_pair_is_not_waited_for(monkeypatch):
    slow = Agent("nvidia", "unused", json.dumps(REPORT), delay=1.0)
    quick = Agent("groq", "unused", json.dumps({**REPORT, "verdict": "quick"}))
    started = time.monotonic()
    report = Assistant([slow, quick]).fact_check("q", "A.", [chunk()])
    assert report.verdict == "quick" and time.monotonic() - started < 0.8
    monkeypatch.setattr(service_module, "FACT_CHECK_SECONDS", 0.2)
    started = time.monotonic()
    late = Assistant([Agent("gemini", "", json.dumps(REPORT), delay=2)]).fact_check(
        "q", "A.", [chunk()]
    )
    assert late is None and time.monotonic() - started < 1.5


def test_any_answer_can_be_checked_through_ask(plain_client):
    from app.assistant import get_assistant
    from app.db import get_db
    from app.embedding import get_embedder
    from app.main import app

    gemini = Agent(
        "gemini",
        "unused",
        json.dumps({**REPORT, "faithful": True, "unsupported": [], "citation_errors": []}),
    )
    app.dependency_overrides[get_assistant] = lambda: Assistant([gemini])
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_embedder] = lambda: None
    try:
        body = {
            "question": "How is it checked?",
            "task": "check",
            "answer": "In constant time [itsdangerous/signer.py:227-228].",
            "chunks": [chunk().model_dump()],
        }
        checked = plain_client.post("/ask", json=body)
        missing = plain_client.post("/ask", json={**body, "answer": " "})
    finally:
        app.dependency_overrides.pop(get_assistant, None)
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_embedder, None)
    assert checked.status_code == 200
    data = checked.json()
    assert data["fact_check"]["faithful"] is True
    assert data["citations"][0]["verified"] is True
    assert len(gemini.calls) == 1  # a check, not a new answer
    assert missing.status_code == 422
