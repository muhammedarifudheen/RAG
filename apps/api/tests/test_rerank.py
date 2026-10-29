"""Reranking: a relevance judge scores each excerpt, and the excerpts are reordered and cut."""

import json
import re
import time

from app.assistant import service as service_module
from app.assistant.prompt import rank_prompt
from app.assistant.rerank import parse_judgement, parse_ranking, rerank
from app.assistant.service import Assistant, Options
from app.schemas import AskRequest, CodeChunk, Reranking


def chunk(symbol_id, score, snippet="pass"):
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
        snippet=snippet,
        snippet_end_line=symbol_id + 1,
        truncated=False,
        citation=f"[a.py:{symbol_id}-{symbol_id + 1}]",
    )


def test_the_judges_reply_is_read():
    assert parse_judgement('{"score": 8, "reason": "Defines the check."}') == (
        8,
        "Defines the check.",
    )
    assert parse_judgement('Sure!\n```json\n{"score": "7", "reason": "close"}\n```') == (7, "close")
    assert parse_judgement('{"score": 14, "reason": "x"}') == (10, "x")
    assert parse_judgement('{"score": 6, "reason": "says "hi" twice"}') == (6, "")
    assert parse_judgement("It is quite relevant.") is None


def test_judged_excerpts_are_ordered_by_score_and_the_weak_left_out():
    chunks = [chunk(1, 0.9), chunk(2, 0.8), chunk(3, 0.7), chunk(4, 0.6), chunk(5, 0.5)]
    verdicts = {1: (2, "unrelated"), 2: (6, "near"), 3: (9, "answers it"), 4: (6, "")}
    ranked = rerank(chunks, verdicts, cutoff=4, limit=3)
    assert [c.symbol_id for c in ranked] == [3, 2, 4]  # 2 before 4: same score, more similar
    assert (ranked[0].relevance, ranked[0].relevance_reason) == (9, "answers it")
    assert ranked[2].relevance_reason is None
    # Four of five judged: the fifth, not reached in time, goes like those turned down.
    assert [c.symbol_id for c in rerank(chunks, verdicts, 4, 10)] == [3, 2, 4]
    # Only two of five judged: the others are kept after them, in search order.
    few = {3: (9, ""), 1: (1, "")}
    assert [c.symbol_id for c in rerank(chunks, few, 4, 10)] == [3, 2, 4, 5]
    # No verdicts at all: the search order.
    assert [c.symbol_id for c in rerank(chunks, {}, 4, 2)] == [1, 2]


class Judge:
    """Scores an excerpt by a number in its code, after `delay` seconds."""

    def __init__(self, name, delay=0.0, reply=None):
        self.name, self.label, self.delay, self.reply = name, name.title(), delay, reply
        self.models = [f"{name}-1"]
        self.prompts = []

    def searches(self, model):
        return False

    def stream(self, model, system, turns, outcome, *, web, temperature=None, max_tokens=None):
        self.prompts.append(turns[-1].content)
        time.sleep(self.delay)
        outcome.model = model
        if self.reply is not None:
            yield self.reply
            return
        score = re.search(r"score_me_(\d+)", turns[-1].content)
        yield json.dumps({"score": int(score.group(1)) if score else 0, "reason": "seen"})


def test_each_excerpt_is_judged_with_the_users_prompt_in_parallel():
    groq = Judge("groq", delay=0.5)
    chunks = [chunk(i, 0.5, f"x = 'score_me_{i}'") for i in range(1, 7)]
    started = time.monotonic()
    verdicts = Assistant([groq], reranker=True).judge_chunks("how is x set", chunks)
    assert time.monotonic() - started < 2.5  # six half-second calls at once
    assert verdicts == {i: (i, "seen") for i in range(1, 7)}
    assert len(groq.prompts) == 6
    first = groq.prompts[0]
    assert first.startswith("You are a relevance judge.\n\nUser question: how is x set\n")
    assert "Candidate chunk: a.py:" in first
    assert first.endswith('Return only: {"score": <int>, "reason": "<one line>"}')


def test_slow_services_never_judge_and_slow_judges_are_not_waited_for(monkeypatch):
    horde = Judge("horde")
    assert Assistant([horde], reranker=True).judge_chunks("q", [chunk(1, 0.5)]) == {}
    assert horde.prompts == []
    monkeypatch.setattr(service_module, "JUDGE_SECONDS", 0.2)
    started = time.monotonic()
    late = Assistant([Judge("groq", delay=2)], reranker=True).judge_chunks("q", [chunk(1, 0.5)])
    assert late == {} and time.monotonic() - started < 1.5


def test_an_unreadable_verdict_is_tried_on_another_model():
    rambling = Judge("groq", reply="Very relevant indeed.")
    scoring = Judge("cerebras")
    verdicts = Assistant([rambling, scoring], reranker=True).judge_chunks(
        "q", [chunk(1, 0.5, "score_me_7")]
    )
    assert verdicts == {1: (7, "seen")}


def test_the_reranking_is_reported_and_kept_with_the_answer():
    summary = Reranking(candidates=16, judged=15, kept=6, cutoff=4)
    events = list(
        Assistant([Judge("gemini", reply="The answer.")]).respond(
            "q", [], (), "auto", Options(reranking=summary)
        )
    )
    assert events[0] == ("judged", summary.model_dump())
    assert events[-1][1]["reranking"] == summary.model_dump()


def test_turning_reranking_off_or_changing_the_cutoff_sends_the_question_to_the_assistant():
    assert AskRequest(question="q", rerank=False).for_assistant
    assert AskRequest(question="q", rerank_cutoff=7).for_assistant
    assert not AskRequest(question="q").for_assistant


def test_the_rankers_prompt_numbers_the_passages():
    prompt = rank_prompt("how is x set", ["a.py:1-2 (function f)\nx = 1", "b.py:3-4 (function g)"])
    assert prompt.startswith(
        "Rank the following passages by how directly they answer the question.\n"
        "Question: how is x set\n\nPassages:\n[1] a.py:1-2 (function f)\nx = 1\n"
        "[2] b.py:3-4 (function g)\n\nReturn a JSON list of passage numbers"
    )
    assert "{passage_1}" not in prompt and "..." not in prompt


def test_the_rankers_reply_is_read():
    assert parse_ranking('{"ranking": [3, 1, 2], "justification": "Defines it."}', 3) == (
        [2, 0, 1],
        "Defines it.",
    )
    assert parse_ranking("```json\n[2, 1]\n```\nJustification: [2] answers it.", 3) == (
        [1, 0, 2],  # 3 was left out: it goes last
        "[2] answers it.",
    )
    assert parse_ranking('{"order": ["2", "2", "9", "1"]}', 2) == ([1, 0], "")
    assert parse_ranking("Passage two is best.", 2) is None


class Ranker(Judge):
    def __init__(self, name, reply, delay=0.0):
        super().__init__(name, delay=delay, reply=reply)


def test_a_fast_model_ranks_the_kept_excerpts_together(monkeypatch):
    groq = Ranker("groq", '{"ranking": [2, 1], "justification": "It compares."}')
    chunks = [chunk(1, 0.6), chunk(2, 0.5)]
    assert Assistant([groq]).rank_chunks("q", chunks) == ([1, 0], "It compares.")
    assert len(groq.prompts) == 1 and groq.prompts[0].startswith("Rank the following passages")
    assert Assistant([groq]).rank_chunks("q", chunks[:1]) is None  # nothing to order
    horde = Ranker("horde", '{"ranking": [2, 1]}')
    assert Assistant([horde]).rank_chunks("q", chunks) is None and horde.prompts == []
    monkeypatch.setattr(service_module, "RANK_SECONDS", 0.2)
    started = time.monotonic()
    assert Assistant([Ranker("groq", "[2, 1]", delay=2)]).rank_chunks("q", chunks) is None
    assert time.monotonic() - started < 1.5


def test_turning_the_ranker_off_sends_the_question_to_the_assistant():
    assert AskRequest(question="q", rank_passages=False).for_assistant


# --- Through /ask, against the test database --------------------------------------------


class Recording(Judge):
    """Judges excerpts mentioning format_name 9, others 1; otherwise answers and records
    the excerpts it was given."""

    def __init__(self):
        super().__init__("groq")
        self.asked = []

    def stream(self, model, system, turns, outcome, *, web, temperature=None, max_tokens=None):
        outcome.model = model
        content = turns[-1].content
        if content.startswith("You are a relevance judge."):
            chunk_part = content.split("Candidate chunk:", 1)[1]
            yield json.dumps({"score": 9 if "format_name" in chunk_part else 1, "reason": "r"})
            return
        if content.startswith("Rank the following passages"):
            count = len(re.findall(r"^\[\d+\] ", content, re.MULTILINE))
            yield json.dumps({"ranking": list(range(count, 0, -1)), "justification": "last"})
            return
        self.asked.append(content)
        yield "Answer."


def test_ask_gives_the_model_only_the_excerpts_the_judge_kept(client):
    from app.assistant import get_assistant
    from app.main import app

    recording = Recording()
    app.dependency_overrides[get_assistant] = lambda: Assistant([recording], reranker=True)
    try:
        judged = client.post(
            "/ask", json={"question": "format name of a user", "style": "concise"}
        ).json()
        off = client.post(
            "/ask", json={"question": "format name of a user", "rerank": False}
        ).json()
    finally:
        app.dependency_overrides.pop(get_assistant, None)
    assert judged["reranking"]["candidates"] >= judged["reranking"]["kept"] >= 1
    assert all(c["relevance"] == 9 for c in judged["chunks"])
    assert any(c["name"].endswith("format_name") for c in judged["chunks"])
    assert judged["reranking"]["ranked"] == (judged["reranking"]["kept"] >= 2)
    assert off["reranking"] is None
    assert all(c["relevance"] is None for c in off["chunks"])
