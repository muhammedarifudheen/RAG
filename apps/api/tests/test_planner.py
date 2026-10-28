"""Query planning: several knowledge-base searches per question, fused into one ranking."""

import time

from app.assistant import service as service_module
from app.assistant.planner import fuse, parse_queries
from app.assistant.service import Assistant, Options
from app.schemas import AskRequest, CodeChunk

PLAN = (
    '{"queries": ["How does itsdangerous check a signature?", "itsdangerous signature verify", '
    '"itsdangerous recomputes the HMAC and compares it in constant time", '
    '"signature validation in itsdangerous Signer"]}'
)


def chunk(symbol_id, score):
    return CodeChunk(
        symbol_id=symbol_id,
        name=f"f{symbol_id}",
        kind="function",
        file="a.py",
        language="python",
        start_line=symbol_id,
        end_line=symbol_id + 1,
        signature=f"def f{symbol_id}()",
        score=score,
        snippet="pass",
        snippet_end_line=symbol_id + 1,
        truncated=False,
        citation=f"[a.py:{symbol_id}-{symbol_id + 1}]",
    )


def test_the_plan_is_read_and_the_question_comes_first():
    queries = parse_queries(f"Here you go:\n```json\n{PLAN}\n```", "how is a signature checked")
    assert queries[0] == "how is a signature checked"
    assert queries[1:] == [
        "How does itsdangerous check a signature?",
        "itsdangerous signature verify",
        "itsdangerous recomputes the HMAC and compares it in constant time",
        "signature validation in itsdangerous Signer",
    ]


def test_repeats_and_bad_replies_leave_just_the_question():
    assert parse_queries('{"queries": ["What is HMAC?", "hmac"]}', "what is HMAC") == [
        "what is HMAC",
        "hmac",
    ]
    assert parse_queries("I cannot help with that.", "q") == ["q"]
    assert parse_queries('{"queries": "not a list"}', "q") == ["q"]


def test_results_found_by_several_queries_rank_first_and_keep_their_best_score():
    first = [chunk(1, 0.6), chunk(2, 0.55), chunk(3, 0.5)]
    second = [chunk(3, 0.7), chunk(4, 0.65)]
    third = [chunk(3, 0.4), chunk(1, 0.45)]
    fused = fuse([first, second, third], limit=3)
    assert [c.symbol_id for c in fused] == [3, 1, 4]
    assert fused[0].score == 0.7  # its best similarity, not a fusion score


class Planner:
    def __init__(self, name, reply, delay=0.0):
        self.name, self.label, self.reply, self.delay = name, name.title(), reply, delay
        self.models = [f"{name}-1"]
        self.calls = []

    def searches(self, model):
        return False

    def stream(self, model, system, turns, outcome, *, web, temperature=None, max_tokens=None):
        self.calls.append(system)
        time.sleep(self.delay)
        outcome.model = model
        yield self.reply


def test_a_fast_model_plans_the_searches():
    groq = Planner("groq", PLAN)
    queries = Assistant([groq], planner=True).plan_queries("how is a signature checked")
    assert len(queries) == 5
    assert groq.calls[0].startswith("You are a query planner for a retrieval system.")


def test_slow_services_never_plan_and_a_slow_plan_is_not_waited_for(monkeypatch):
    horde = Planner("horde", PLAN)
    assert Assistant([horde], planner=True).plan_queries("q") == ["q"]
    assert horde.calls == []
    monkeypatch.setattr(service_module, "PLAN_SECONDS", 0.2)
    started = time.monotonic()
    late = Assistant([Planner("groq", PLAN, delay=2)], planner=True).plan_queries("q")
    assert late == ["q"] and time.monotonic() - started < 1.5


def test_the_planned_searches_are_reported_and_kept_with_the_answer():
    answering = Planner("gemini", "The answer.")
    events = list(
        Assistant([answering]).respond(
            "q", [], (), "auto", Options(search_queries=("q", "keywords", "hyde"))
        )
    )
    assert events[0] == ("planned", {"queries": ["q", "keywords", "hyde"]})
    assert events[-1][1]["search_queries"] == ["q", "keywords", "hyde"]
    plain = list(Assistant([Planner("gemini", "x")]).respond("q", [], ()))
    assert plain[0][0] == "route" and plain[-1][1]["search_queries"] == []


def test_turning_planning_off_sends_the_question_to_the_assistant():
    assert AskRequest(question="q", plan_queries=False).for_assistant


# --- Through /ask, against the test database --------------------------------------------


class Recording(Planner):
    """Plans when asked by the planner prompt; otherwise answers and records the excerpts."""

    def __init__(self):
        super().__init__("groq", "")
        self.asked = []

    def stream(self, model, system, turns, outcome, *, web, temperature=None, max_tokens=None):
        outcome.model = model
        if system.startswith("You are a query planner"):
            yield '{"queries": ["format_name title case", "names are stripped and title-cased"]}'
            return
        self.asked.append(turns[-1].content)
        yield "Answer."


def test_ask_searches_with_every_planned_query(client):
    from app.assistant import get_assistant
    from app.main import app

    recording = Recording()
    app.dependency_overrides[get_assistant] = lambda: Assistant([recording], planner=True)
    try:
        response = client.post(
            "/ask", json={"question": "How are user names formatted?", "style": "concise"}
        )
        off = client.post(
            "/ask",
            json={"question": "How are user names formatted?", "plan_queries": False},
        )
    finally:
        app.dependency_overrides.pop(get_assistant, None)
    assert response.status_code == 200
    assert response.json()["search_queries"] == [
        "How are user names formatted?",
        "format_name title case",
        "names are stripped and title-cased",
    ]
    assert "format_name" in recording.asked[0]  # the fused search found the function
    assert off.json()["search_queries"] == []
