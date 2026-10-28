"""The chat's AI, retrieval and generation controls, chosen per question."""

from types import SimpleNamespace

import pytest

from app.assistant.service import Assistant, Options
from app.schemas import AskRequest, CodeChunk


class Agent:
    def __init__(self, name, replies):
        self.name, self.label = name, name.title()
        self.replies = dict(replies)
        self.models = list(self.replies)
        self.calls = []

    def searches(self, model):
        return False

    def stream(self, model, system, turns, outcome, *, web, temperature=None, max_tokens=None):
        self.calls.append(
            SimpleNamespace(
                model=model,
                system=system,
                turns=turns,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        )
        outcome.model = model
        yield self.replies[model]


class Searcher:
    def __init__(self):
        self.queries = []

    def search(self, query, recent=False):
        self.queries.append(query)
        return []


def ask(assistant, question="What is HMAC?", chunks=(), **options):
    return list(assistant.respond(question, list(chunks), (), "auto", Options(**options)))


def merges(agent):
    return [c.model for c in agent.calls if "Several independent" in c.system]


def test_only_the_chosen_services_answer():
    gemini, groq = Agent("gemini", {"g1": "G."}), Agent("groq", {"q1": "Q."})
    events = ask(Assistant([gemini, groq], council_size=12, council_grace=0.2), services=("groq",))
    assert events[0][1]["providers"] == ["groq"]
    assert gemini.calls == []
    assert events[-1][1]["answer"] == "Q."


def test_choosing_only_unavailable_services_is_refused():
    events = ask(Assistant([Agent("gemini", {"g1": "G."})]), services=("cerebras",))
    name, data = events[-1]
    assert name == "error" and data["status"] == 422


def test_a_council_of_one_is_one_model_answering():
    gemini, groq = Agent("gemini", {"g1": "G."}), Agent("groq", {"q1": "Q."})
    events = ask(Assistant([gemini, groq], council_size=12), council_size=1)
    assert "merging" not in [name for name, _ in events]
    assert len(gemini.calls) == 1 and groq.calls == []


def test_the_council_size_limits_the_agents_seated():
    gemini = Agent("gemini", {"g1": "1.", "g2": "2.", "g3": "3."})
    events = ask(Assistant([gemini], council_size=12, council_grace=0.2), council_size=2)
    seated = [d for name, d in events if name == "agent" and d["state"] == "thinking"]
    assert len(seated) == 2


def test_the_chosen_merger_merges():
    gemini, groq = Agent("gemini", {"g1": "G."}), Agent("groq", {"q1": "Q."})
    assistant = Assistant([gemini, groq], council_size=12, council_grace=0.2)
    ask(assistant, merger="groq")
    assert merges(groq) == ["q1"] and merges(gemini) == []


def test_web_search_can_be_turned_off():
    searcher = Searcher()
    assistant = Assistant([Agent("gemini", {"g1": "G."})], web=searcher)
    ask(assistant, web_search=False)
    assert searcher.queries == []
    ask(assistant)
    assert len(searcher.queries) == 1


def test_the_relevance_threshold_decides_which_excerpts_are_shown():
    chunk = CodeChunk(
        symbol_id=1,
        name="f",
        kind="function",
        file="a.py",
        language="python",
        start_line=1,
        end_line=2,
        signature="def f()",
        score=0.35,
        snippet="def f(): pass",
        snippet_end_line=2,
        truncated=False,
        citation="[a.py:1-2]",
    )
    shown = Agent("gemini", {"g1": "G."})
    ask(Assistant([shown], min_score=0.3), chunks=[chunk], min_score=0.5)
    assert "a.py" not in shown.calls[0].turns[-1].content
    kept = Agent("gemini", {"g1": "G."})
    ask(Assistant([kept], min_score=0.3), chunks=[chunk], min_score=0.2)
    assert "a.py" in kept.calls[0].turns[-1].content


def test_the_answer_length_goes_to_every_model():
    gemini = Agent("gemini", {"g1": "G."})
    ask(Assistant([gemini]), max_tokens=500)
    assert gemini.calls[0].max_tokens == 500


@pytest.mark.parametrize(
    ("format", "phrase"), [("plain", "plain text"), ("json", "one valid JSON object")]
)
def test_the_output_format_is_asked_for(format, phrase):
    gemini = Agent("gemini", {"g1": "G."})
    ask(Assistant([gemini]), format=format)
    assert phrase in gemini.calls[0].system


def test_each_agents_draft_comes_back_when_asked_for():
    gemini, groq = Agent("gemini", {"g1": "Gemini's draft."}), Agent("groq", {"q1": "Groq's."})
    assistant = Assistant([gemini, groq], council_size=12, council_grace=0.2)
    done = ask(assistant, include_drafts=True)[-1][1]
    drafts = {d["agent"]: d for d in done["drafts"]}
    assert drafts["Gemini · g1"]["answer"] == "Gemini's draft."
    assert drafts["Groq · q1"]["seconds"] >= 0
    assert ask(assistant)[-1][1]["drafts"] == []


@pytest.mark.parametrize(
    "field",
    [
        {"services": ["groq"]},
        {"council_size": 3},
        {"merger": "groq"},
        {"use_sources": False},
        {"min_score": 0.5},
        {"web_search": False},
        {"max_tokens": 800},
        {"format": "json"},
        {"include_drafts": True},
    ],
)
def test_every_control_sends_the_question_to_the_assistant(field):
    assert AskRequest(question="q", **field).for_assistant
    assert not AskRequest(question="q").for_assistant
