"""The gap finder: what the knowledge base covers and lacks for a question, and what to add."""

from types import SimpleNamespace

from app.assistant.gaps import suggested_source
from app.assistant.prompt import audit_prompt, gap_prompt
from app.assistant.service import Assistant

REPORT = """\
1. **What the KB covers well:** itsdangerous's signing and timestamps.
2. **What is missing:** nothing on Flask's session cookie.
3. **The single best source to add next:** the Flask repository, \
https://github.com/pallets/flask.
"""


class Agent:
    def __init__(self, reply):
        self.name, self.label, self.models = "nvidia", "NVIDIA", ["n1"]
        self.reply, self.calls = reply, []

    def searches(self, model):
        return False

    def stream(self, model, system, turns, outcome, *, web, temperature=None, max_tokens=None):
        self.calls.append(SimpleNamespace(system=system, content=turns[-1].content))
        outcome.model = model
        yield self.reply


def test_the_prompts_are_the_users_with_the_sources_filled_in():
    prompt = gap_prompt("How do Flask sessions work?", "- [1] itsdangerous (repo)")
    assert prompt.startswith(
        "Given this knowledge base (sources listed below) and the user's question, identify:\n"
        "1. What the KB covers well."
    )
    assert prompt.endswith(
        "Sources: \n- [1] itsdangerous (repo)\nQuestion: How do Flask sessions work?"
    )
    audit = audit_prompt("- [1] itsdangerous (repo)")
    assert audit.startswith("You are auditing a RAG knowledge base.\nFor each source, report:")
    assert audit.endswith("Sources: \n- [1] itsdangerous (repo)\nReturn a markdown table.")


def test_the_suggested_source_is_the_link_in_the_third_part():
    assert suggested_source(REPORT) == "https://github.com/pallets/flask"
    assert suggested_source("### 3. Best source\n<https://flask.palletsprojects.com/>") == (
        "https://flask.palletsprojects.com/"
    )
    # A link in the first part is not the suggestion.
    assert suggested_source("1. Covers https://a.example\n3. Add the Flask docs.") is None
    assert suggested_source("No numbered parts.") is None


def test_the_gap_finder_reports_with_who_found_it():
    agent = Agent(REPORT)
    report, found_by = Assistant([agent]).find_gaps("How do Flask sessions work?", "- [1] x")
    assert report.startswith("1. **What the KB covers well:**")
    assert found_by == "NVIDIA · n1"
    assert agent.calls[0].content.startswith("Given this knowledge base")


def test_ask_finds_the_gaps(plain_client, monkeypatch):
    from app.assistant import get_assistant
    from app.db import get_db
    from app.embedding import get_embedder
    from app.main import app
    from app.routers import search as search_router

    monkeypatch.setattr(search_router, "source_catalog", lambda db: "- [1] itsdangerous (repo)")
    app.dependency_overrides[get_assistant] = lambda: Assistant([Agent(REPORT)])
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_embedder] = lambda: None
    try:
        body = plain_client.post(
            "/ask", json={"question": "How do Flask sessions work?", "task": "gaps"}
        ).json()
    finally:
        for dependency in (get_assistant, get_db, get_embedder):
            app.dependency_overrides.pop(dependency, None)
    assert body["gaps"]["suggestion_url"] == "https://github.com/pallets/flask"
    assert body["gaps"]["report"] == body["answer"]
    assert body["gaps"]["found_by"] == "NVIDIA · n1"


def test_the_catalog_lists_each_source_with_its_size_and_files(db):
    from app.services.catalog import source_catalog

    catalog = source_catalog(db)
    line = next(line for line in catalog.splitlines() if "acme/pkg" in line)
    assert "(repo; https://github.com/acme/pkg; added " in line
    assert "files" in line and "passages" in line
    assert "pkg/models.py" in catalog
