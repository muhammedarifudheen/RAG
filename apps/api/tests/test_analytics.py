"""Analytics and the rest of the 100x API: feedback, analytics.query, CSV, /v1
embeddings, the agent's analytics, health and fetch tools, admin keys, multilingual."""

import json
from types import SimpleNamespace

from seed import FakeEmbedder

from app.assistant.agent import ResearchTools, parse_action
from app.assistant.prompt import ANSWER_FORMAT
from app.assistant.service import Assistant, Options
from app.embedding import get_embedder
from app.main import app
from app.schemas import CodeChunk
from app.services.analytics import as_csv, as_text


def test_the_agents_system_tools_are_read():
    assert parse_action('{"tool": "analytics", "metric": "gaps", "window": 30}').arguments == {
        "window": 30,
        "filter": None,
    }
    assert parse_action('{"tool": "health"}').tool == "health"
    assert (
        parse_action('{"tool": "fetch", "url": "https://docs.example.com/x"}').name
        == "https://docs.example.com/x"
    )
    assert parse_action('{"tool": "fetch", "url": "file:///etc/passwd"}') is None


def page():
    return CodeChunk(
        symbol_id=-5, name="web/docs.example.com/tokens", kind="section", signature=None,
        file="web/docs.example.com/tokens", language="markdown", start_line=1, end_line=2,
        score=0.5, snippet="Tokens expire after max_age seconds.\nThe default is none.",
        snippet_end_line=2, truncated=False, citation="[web/docs.example.com/tokens:1-2]",
    )  # fmt: skip


class Researcher:
    def __init__(self, script):
        self.name, self.label, self.models = "groq", "Groq", ["g1"]
        self.script, self.calls = list(script), []

    def searches(self, model):
        return False

    def stream(self, model, system, turns, outcome, *, web, temperature=None, max_tokens=None):
        self.calls.append(SimpleNamespace(system=system, turns=list(turns)))
        outcome.model = model
        if system.startswith("Call one tool per reply"):
            yield self.script.pop(0) if self.script else '{"tool": "done"}'
            return
        yield "Tokens expire after max_age [web/docs.example.com/tokens:1-2]."


def test_the_agent_queries_analytics_checks_health_and_fetches_allowed_pages():
    script = [
        json.dumps({"tool": "analytics", "metric": "top_questions", "window": 7}),
        json.dumps({"tool": "health"}),
        json.dumps({"tool": "fetch", "url": "https://docs.example.com/tokens"}),
    ]
    asked = []
    tools = ResearchTools(
        search=lambda q: [],
        read=lambda p, s, e: None,
        analytics=lambda metric, window, found: (
            asked.append((metric, window)) or "top_questions: - q: 3"
        ),
        health=lambda: "Overall health 80/100",
        fetch=lambda url: page(),
    )
    agent = Researcher(script)
    events = list(
        Assistant([agent]).respond(
            "What do people ask most?", [], (), "auto", Options(research=tools)
        )
    )
    assert (
        '{"tool": "analytics"' in agent.calls[0].system
        and '{"tool": "fetch"' in agent.calls[0].system
    )
    assert asked == [("top_questions", 7)]
    steps = [(d["tool"], d["result"]) for n, d in events if n == "researching"]
    assert steps == [
        ("analytics", "top_questions over 7 days"),
        ("health", "checked"),
        ("fetch", "2 lines"),
    ]
    done = events[-1][1]
    assert done["citations"][0]["verified"] is True


def test_answers_are_in_the_questions_language_with_sources_cited_in_theirs():
    assert (
        "Answer in the language of the question; quote and cite the sources in their own"
        in ANSWER_FORMAT
    )


def test_results_become_text_and_csv():
    result = {
        "metric": "slowest",
        "window": 7,
        "rows": [{"question": "q", "latency_ms": 900, "mode": "ASK"}],
    }
    assert (
        as_text(result)
        == "slowest over the last 7 days:\n- question: q, latency_ms: 900, mode: ASK"
    )
    assert as_csv(result).splitlines() == ["question,latency_ms,mode", "q,900,ASK"]


def test_embeddings_are_openai_compatible(plain_client):
    app.dependency_overrides[get_embedder] = FakeEmbedder
    data = plain_client.post(
        "/v1/embeddings", json={"input": ["signer", "hmac"], "model": "x"}
    ).json()
    assert data["object"] == "list" and [d["index"] for d in data["data"]] == [0, 1]
    assert len(data["data"][0]["embedding"]) == 384
    assert plain_client.post("/v1/embeddings", json={"input": []}).status_code == 422


# --- With the database (run in CI) ---------------------------------------------------


def test_feedback_and_analytics_follow_the_answers(client):
    client.post("/ask", json={"question": "Who calls format_name?", "style": "concise"})
    client.post("/ask", json={"question": "Who calls format_name?", "style": "concise"})
    # Answers the database gives directly are not logged; log one the usual way.
    from app.db import SessionLocal
    from app.models import AnswerLog

    with SessionLocal() as db:
        db.add(AnswerLog(question="What is the tagline?", state="absent", route="sources", citations=2,
                         verified=1, latency_ms=4200, mode="ASK"))  # fmt: skip
        db.commit()
    assert client.post("/feedback", json={"question": "What is the tagline?", "rating": "down",
                                          "reason": "wrong"}).status_code == 204  # fmt: skip
    failing = client.get("/analytics", params={"metric": "failing"}).json()["rows"]
    assert (
        failing[0]["question"] == "What is the tagline?"
        and failing[0]["why"] == "thumbs down: wrong"
    )
    gaps = client.get("/analytics", params={"metric": "gaps"}).json()["rows"]
    assert any(g["question"] == "What is the tagline?" for g in gaps)
    slowest = client.get("/analytics", params={"metric": "slowest"}).json()["rows"]
    assert slowest[0]["latency_ms"] >= 4200
    drift = client.get("/analytics", params={"metric": "drift", "window": 14}).json()["rows"]
    assert drift and {"week", "hit_rate", "faithfulness", "approval"} <= set(drift[-1])
    csv = client.get("/export/analytics.csv", params={"metric": "failing"})
    assert csv.headers["content-type"].startswith("text/csv") and "thumbs down" in csv.text
    assert (
        client.post("/feedback", json={"question": "never asked", "rating": "up"}).status_code
        == 404
    )
    assert client.get("/v1/health").json()["sources"]
    assert client.get("/v1/graph", params={"node": "format_name"}).json()["nodes"]


def test_an_admin_key_can_query_analytics(client, monkeypatch):
    from app.config import settings

    made = client.post("/keys", json={"name": "ops", "scope": "admin"}).json()
    monkeypatch.setattr(settings, "admin_token", "secret")
    assert client.get("/analytics", params={"metric": "feedback"}).status_code == 401
    allowed = client.get(
        "/analytics", params={"metric": "feedback"}, headers={"X-Atlas-Key": made["key"]}
    )
    assert allowed.status_code == 200
    via_bearer = client.get("/v1/analytics", params={"metric": "feedback"},
                            headers={"Authorization": f"Bearer {made['key']}"})  # fmt: skip
    assert via_bearer.status_code == 200
