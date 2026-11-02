"""The knowledge graph: questions in words, the research agent's graph tool, and (with the
database) neighbours, paths, related nodes and what ingest extracts."""

import json
from types import SimpleNamespace

from app.assistant.agent import ResearchTools, parse_action
from app.assistant.modes import classify_mode
from app.assistant.service import Assistant, Options
from app.schemas import CodeChunk
from app.services.kg import parse_question


def test_graph_questions_are_recognised_and_routed_to_explore():
    cases = {
        "What is the shortest path between Signer and want_bytes?": (
            "path",
            ["Signer", "want_bytes"],
        ),
        "How is Signer connected to BadSignature?": ("path", ["Signer", "BadSignature"]),
        "What does unsign depend on?": ("depends", ["unsign"]),
        "What contradicts HMAC (Wikipedia)?": ("contradicts", ["HMAC (Wikipedia)"]),
        "What supersedes acme/pkg?": ("supersedes", ["acme/pkg"]),
        "Who calls verify_signature?": ("callers", ["verify_signature"]),
    }
    for question, expected in cases.items():
        assert parse_question(question) == expected
        assert classify_mode(question) == "EXPLORE"
    assert parse_question("What is HMAC?") is None


def test_the_graph_tool_is_read_in_its_forms():
    action = parse_action('{"tool": "graph", "node": "Signer.unsign", "depth": 2, "edge": "calls"}')
    assert (action.tool, action.name, action.arguments) == (
        "graph",
        "Signer.unsign",
        {"depth": 2, "edge": "calls"},
    )
    assert parse_action('{"tool": "graph", "name": "x", "depth": 9}').arguments["depth"] == 3
    assert parse_action('{"tool": "graph"}') is None


def excerpt():
    return CodeChunk(
        symbol_id=7, name="Signer.verify_signature", kind="method", file="a/signer.py",
        language="python", start_line=30, end_line=40, signature=None, score=1.0,
        snippet="def verify_signature(...): ...", snippet_end_line=40, truncated=False,
        citation="[a/signer.py:30-40]",
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
        yield "unsign calls verify_signature [a/signer.py:30-40]."


def test_the_agent_walks_the_graph_and_can_cite_what_it_reached():
    walked = []

    def graph(node, depth, edge):
        walked.append((node, depth, edge))
        return (
            "Around Signer.unsign:\n- Signer.unsign —calls→ verify_signature [a/signer.py:30-40]",
            [excerpt()],
        )

    agent = Researcher([json.dumps({"tool": "graph", "node": "Signer.unsign", "edge": "calls"})])
    tools = ResearchTools(search=lambda q: [], read=lambda p, s, e: None, graph=graph)
    events = list(
        Assistant([agent]).respond(
            "What does unsign call?", [], (), "auto", Options(research=tools)
        )
    )
    assert '"tool": "graph"' in agent.calls[0].system
    assert walked == [("Signer.unsign", 1, "calls")]
    assert "Result of graph:\nAround Signer.unsign" in agent.calls[1].turns[-1].content
    done = events[-1][1]
    assert done["chunks"][0]["file"] == "a/signer.py"
    assert done["citations"][0]["verified"] is True


# --- With the database (run in CI) ---------------------------------------------------


def test_the_graph_answers_neighbours_paths_and_callers(client):
    around = client.get("/kg", params={"node": "format_name", "depth": 1}).json()
    labels = {n["label"] for n in around["nodes"]}
    assert "format_name" in labels and "create_user" in labels
    assert any(e["kind"] == "calls" for e in around["edges"])
    callers = client.get(
        "/kg/related", params={"node": "format_name", "relation": "callers"}
    ).json()
    assert "create_user" in {n["label"] for n in callers["nodes"]}
    joined = client.get("/kg/path", params={"from": "create_user", "to": "format_name"}).json()
    assert len(joined["path"]) == 2
    detail = client.get("/kg/node", params={"node": "format_name"}).json()
    assert (
        detail["citation"].startswith("[pkg/models.py:") and "def format_name" in detail["snippet"]
    )
    assert client.get("/kg", params={"node": "no_such_thing_anywhere"}).status_code == 404
    overview = client.get("/kg/overview").json()
    assert overview["nodes"] and {"type", "source_id"} <= set(overview["nodes"][0])


def test_a_graph_question_is_answered_from_the_graph_in_explore(client):
    answered = client.post(
        "/ask",
        json={
            "question": "What is the shortest path between create_user and format_name?",
            "style": "concise",
        },
    ).json()
    assert answered["mode"] == "EXPLORE"
    assert answered["answer"].startswith("**Shortest path (1 steps):**")
    assert answered["citations"] and all(c["verified"] for c in answered["citations"])
