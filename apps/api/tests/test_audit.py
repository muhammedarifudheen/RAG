"""The knowledge-base health check: written by a model, kept, and shown with /health."""

from types import SimpleNamespace

import pytest

from app.assistant.service import Assistant
from app.config import settings

TABLE = (
    "| Source | Coverage | Staleness | Redundancy | Gaps |\n"
    "|---|---|---|---|---|\n"
    "| acme/pkg | user names | current | none | 1. 2. 3. |"
)


class Auditor:
    def __init__(self, reply=TABLE):
        self.name, self.label, self.models = "nvidia", "NVIDIA", ["n1"]
        self.reply, self.calls = reply, []

    def searches(self, model):
        return False

    def stream(self, model, system, turns, outcome, *, web, temperature=None, max_tokens=None):
        self.calls.append(SimpleNamespace(system=system, content=turns[-1].content))
        outcome.model = model
        yield self.reply


def test_the_audit_is_the_models_table():
    auditor = Auditor()
    table, model = Assistant([auditor]).audit_sources("- [1] acme/pkg (repo)")
    assert table == TABLE and model == "NVIDIA · n1"
    assert auditor.calls[0].content.startswith("You are auditing a RAG knowledge base.")
    # A reply without a table is no audit.
    assert Assistant([Auditor("I cannot audit this.")]).audit_sources("- [1] x") is None


@pytest.fixture
def auditing(client):
    from app.assistant import get_assistant
    from app.main import app

    auditor = Auditor()
    app.dependency_overrides[get_assistant] = lambda: Assistant([auditor])
    yield auditor
    app.dependency_overrides.pop(get_assistant, None)


def test_an_audit_is_kept_and_returned_with_the_health_report(client, auditing, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "secret")
    assert client.post("/health").status_code == 401  # admin only

    written = client.post("/health", headers={"Authorization": "Bearer secret"})
    assert written.status_code == 200
    body = written.json()
    assert body["report"] == TABLE and body["model"] == "NVIDIA · n1"
    assert body["sources"] >= 1
    assert "acme/pkg" in auditing.calls[0].content  # the catalog of sources went in

    latest = client.get("/health").json()["knowledge_audit"]
    assert latest["report"] == TABLE
    assert latest["created_at"] == body["created_at"]
