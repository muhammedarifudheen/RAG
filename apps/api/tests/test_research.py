"""Deep research: the agent searches, reads and notes, then the answer is written from it."""

import json
from types import SimpleNamespace

from app.assistant.agent import ResearchTools, parse_action
from app.assistant.router import wants_research
from app.assistant.service import Assistant, Options
from app.schemas import AskRequest, CodeChunk


def chunk(symbol_id, file="itsdangerous/signer.py", start=244, end=254, kind="method"):
    return CodeChunk(
        symbol_id=symbol_id,
        name="Signer.unsign",
        kind=kind,
        file=file,
        language="python",
        start_line=start,
        end_line=end,
        signature=None,
        score=0.7,
        snippet="\n".join(f"line {n}" for n in range(start, end + 1)),
        snippet_end_line=end,
        truncated=False,
        citation=f"[{file}:{start}-{end}]",
    )


def test_tool_calls_are_read_in_their_several_forms():
    assert parse_action('{"tool": "search", "query": "unsign"}').query == "unsign"
    read = parse_action('Reading.\n{"tool": "read", "source_id": "a/b.py", "line_range": "10-40"}')
    assert (read.tool, read.path, read.start, read.end) == ("read", "a/b.py", 10, 40)
    cited = parse_action('{"tool": "read", "source_id": "[a/b.py:5-9]"}')
    assert (cited.path, cited.start, cited.end) == ("a/b.py", 5, 9)
    listed = parse_action('{"tool": "read", "path": "a/b.py", "lines": [300, 1000]}')
    assert (listed.start, listed.end) == (300, 419)  # at most READ_LINES
    assert parse_action('{"tool": "note", "text": "It uses HMAC [a.py:1-2]."}').tool == "note"
    assert parse_action('{"tool": "finish"}').tool == "done"
    assert parse_action("I will search for it.") is None
    assert parse_action('{"tool": "search", "query": ""}') is None


def test_which_questions_are_researched():
    assert wants_research("Compare how Signer and TimestampSigner check a signature")
    assert wants_research("Trace a request from the router to the database layer")
    assert wants_research("What signs a value? And what checks its age?")
    assert not wants_research("What is HMAC?")
    assert not wants_research("How is a signature checked in itsdangerous?")
    assert AskRequest(question="q", research=True).for_assistant
    assert AskRequest(question="q", research=False).for_assistant


class Agent:
    """Runs a scripted research loop; then answers, recording what it was given."""

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
        yield "It verifies the signature [itsdangerous/signer.py:300-310]."


def tools(searched, read):
    def search(query):
        searched.append(query)
        return [chunk(1), chunk(2, start=100, end=110)]

    def read_span(path, start, end):
        read.append((path, start, end))
        return chunk(-5, file=path, start=start, end=end, kind="section")

    return ResearchTools(search=search, read=read_span)


def test_the_agent_searches_reads_and_notes_then_the_answer_uses_what_it_found():
    script = [
        json.dumps({"tool": "search", "query": "unsign verify"}),
        json.dumps(
            {"tool": "read", "source_id": "itsdangerous/signer.py", "line_range": "300-310"}
        ),
        json.dumps({"tool": "note", "text": "verify_signature compares in constant time."}),
        json.dumps({"tool": "done"}),
    ]
    agent, searched, read = Agent(script), [], []
    events = list(
        Assistant([agent]).respond(
            "Trace how unsign verifies a signature",
            [],
            (),
            "auto",
            Options(research=tools(searched, read)),
        )
    )
    steps = [data for name, data in events if name == "researching"]
    assert [(s["tool"], s["result"]) for s in steps] == [
        ("search", "2 results"),
        ("read", "read"),
        ("note", "saved"),
    ]
    assert searched == ["unsign verify"] and read == [("itsdangerous/signer.py", 300, 310)]
    # The user's prompt starts the loop, and each tool's result comes back to the agent.
    first = agent.calls[0].turns[0].content
    assert first.startswith("You are a research agent with tools.\nTools:\n- search(query)")
    assert first.endswith("Question: Trace how unsign verifies a signature")
    assert (
        agent.calls[1]
        .turns[-1]
        .content.startswith("Result of search:\n[itsdangerous/signer.py:244-254]")
    )

    done = events[-1][1]
    assert [s["tool"] for s in done["research_steps"]] == ["search", "read", "note"]
    # The span read comes first among the excerpts, so its citation is checked.
    assert done["chunks"][0]["start_line"] == 300
    assert done["citations"][0]["verified"] is True
    answering = agent.calls[-1].turns[-1].content
    assert (
        "<research_notes>\n- verify_signature compares in constant time.\n</research_notes>"
        in answering
    )


def test_the_agent_stops_at_six_tool_calls():
    script = [json.dumps({"tool": "search", "query": f"q{n}"}) for n in range(10)]
    agent, searched = Agent(script), []
    events = list(
        Assistant([agent]).respond("q", [], (), "auto", Options(research=tools(searched, [])))
    )
    assert len(searched) == 6
    assert len(events[-1][1]["research_steps"]) == 6


def test_a_span_is_read_by_path_or_by_its_end(db):
    from app.services.spans import read_span

    span = read_span(db, "pkg/models.py", 20, 21)
    assert span.citation == "[pkg/models.py:20-21]"
    assert span.snippet.startswith("def format_name")
    assert span.symbol_id < 0
    assert read_span(db, "models.py", 20, 21).file == "pkg/models.py"  # the one ending so
    assert read_span(db, "pkg/models.py", 99999, 100000) is None
    assert read_span(db, "no/such.py", 1, 5) is None
