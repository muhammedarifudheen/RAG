import json
from contextlib import contextmanager
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from app import assistant as assistant_module
from app.assistant import Assistant, AssistantError
from app.assistant.prompt import FOLLOW_UPS, FollowUpSplitter, conversation, system_prompt
from app.assistant.providers import (
    ClaudeProvider,
    GeminiProvider,
    OpenAICompatibleProvider,
    Outcome,
    ProviderError,
    Turn,
)
from app.assistant.router import classify, model_order, provider_order
from app.schemas import ChatTurn, CodeChunk


def chunk(score=0.9, symbol_id=7):
    return CodeChunk(
        symbol_id=symbol_id,
        name="format_name",
        kind="function",
        signature="def format_name(name: str) -> str",
        file="pkg/models.py",
        language="python",
        start_line=20,
        end_line=21,
        score=score,
        snippet="def format_name(name: str) -> str:\n    return name.strip().title()",
        snippet_end_line=21,
        truncated=False,
        citation="[pkg/models.py:20-21]",
    )


# --- Routing --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "score", "route"),
    [
        ("hello!", None, "chat"),
        ("thanks", 0.9, "chat"),
        ("how are user names formatted?", 0.62, "sources"),
        ("why does my python function raise a KeyError?", 0.2, "code"),
        ("what happened in the news today?", None, "current"),
        ("solve 3x + 4 = 19 step by step", None, "reasoning"),
        ("what is the capital of France?", 0.1, "general"),
    ],
)
def test_questions_are_routed_by_type(question, score, route):
    assert classify(question, score) == route


def test_auto_mode_follows_the_route_and_best_mode_the_strength_order():
    available = {"gemini", "groq", "openrouter"}
    assert provider_order("auto", "chat", "claude,gemini,groq", available) == [
        "groq",
        "gemini",
        "openrouter",
    ]
    assert provider_order("auto", "code", "", available) == ["openrouter", "gemini", "groq"]
    # Best: the configured strength order, skipping services without a key.
    assert provider_order("best", "chat", "claude,gemini,openrouter,groq", available) == [
        "gemini",
        "openrouter",
        "groq",
    ]


def test_coding_and_reasoning_models_go_first_for_their_routes():
    models = ["deepseek-chat", "deepseek-r1", "qwen3-coder"]
    assert model_order(models, "code") == ["qwen3-coder", "deepseek-chat", "deepseek-r1"]
    assert model_order(models, "reasoning") == ["deepseek-r1", "deepseek-chat", "qwen3-coder"]
    assert model_order(models, "general") == models


# --- Prompt and follow-ups -------------------------------------------------------


def test_the_conversation_keeps_recent_turns_and_ends_with_the_question_and_excerpts():
    history = [ChatTurn(role="assistant", content="Hi!")] + [
        ChatTurn(role=role, content=f"{role} {i}")
        for i in range(20)
        for role in ("user", "assistant")
    ]
    turns = conversation("and names?", [chunk()], history, keep=4)

    assert [t.role for t in turns] == ["user", "assistant", "user", "assistant", "user"]
    assert turns[0].content == "user 18"
    assert '<excerpt path="pkg/models.py"' in turns[-1].content
    assert turns[-1].content.endswith("Question: and names?")
    # Without excerpts the question goes as it is.
    assert conversation("hi", [], [])[-1].content == "hi"


def test_the_system_prompt_dates_itself_and_asks_for_follow_ups():
    from datetime import date

    prompt = system_prompt(date(2026, 10, 22))
    assert "Today is 2026-10-22." in prompt
    assert FOLLOW_UPS in prompt
    assert "[path:start-end]" in prompt


def test_follow_ups_are_split_off_even_when_the_marker_arrives_in_pieces():
    splitter = FollowUpSplitter()
    pieces = [
        "Paris is the capital.",
        "\n\n<<follo",
        "w-ups>>\n1. Why Paris?\n- How big",
        " is it?\n",
    ]
    streamed = "".join(splitter.feed(p) for p in pieces)
    rest, answer, questions = splitter.finish()

    assert (streamed + rest).strip() == "Paris is the capital."
    assert "<<" not in streamed + rest
    assert answer == "Paris is the capital."
    assert questions == ["Why Paris?", "How big is it?"]


def test_an_answer_without_follow_ups_is_passed_through_whole():
    splitter = FollowUpSplitter()
    streamed = splitter.feed("Just an answer, no list.")
    rest, answer, questions = splitter.finish()
    assert streamed + rest == "Just an answer, no list."
    assert (answer, questions) == ("Just an answer, no list.", [])


def test_a_bolded_marker_leaves_no_stray_asterisks():
    splitter = FollowUpSplitter()
    splitter.feed("An answer.\n\n**<<FOLLOW-UPS>>**\nOne?\nTwo?\nThree?\nFour?")
    _, answer, questions = splitter.finish()
    assert answer == "An answer."
    assert questions == ["One?", "Two?", "Three?"]


# --- The assistant, with stand-in services ----------------------------------------


class FakeProvider:
    def __init__(self, name, replies, web_search=False, models=("m1", "m2")):
        self.name = name
        self.label = name.title()
        self.web_search = web_search
        self.models = list(models)
        self.replies = list(replies)  # one per call: a list of pieces, or an exception
        self.calls = []

    def searches(self, model):
        return self.web_search

    def stream(self, model, system, turns, outcome, *, web):
        self.calls.append(SimpleNamespace(model=model, system=system, turns=turns, web=web))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        outcome.model = f"{model}-v1"
        for piece in reply:
            if isinstance(piece, Exception):
                raise piece
            if isinstance(piece, dict):
                outcome.web_sources.append(piece)
                continue
            yield piece


def run(assistant, question="How are names formatted?", chunks=(), history=(), mode="auto"):
    return list(assistant.respond(question, list(chunks), history, mode))


def test_the_answer_streams_then_arrives_whole_with_citations_and_follow_ups():
    gemini = FakeProvider(
        "gemini",
        [["Title-cased [pkg/models.py:20-21].", f"\n{FOLLOW_UPS}\nWhere?\nWhy?\nHow?"]],
        web_search=True,
    )
    events = run(Assistant([gemini]), chunks=[chunk()])

    names = [name for name, _ in events]
    assert names[0] == "route" and names[-1] == "done"
    assert set(names[1:-1]) == {"delta"}
    streamed = "".join(data["text"] for name, data in events if name == "delta")
    assert streamed.strip() == "Title-cased [pkg/models.py:20-21]."

    done = events[-1][1]
    assert done["answer"] == "Title-cased [pkg/models.py:20-21]."
    assert done["citations"][0]["verified"] is True
    assert done["suggestions"] == ["Where?", "Why?", "How?"]
    assert (done["provider"], done["model"], done["route"]) == ("Gemini", "m1-v1", "sources")
    assert gemini.calls[0].web is True  # Gemini may search the web


def test_a_failing_service_hands_over_to_the_next_without_the_reader_seeing_it():
    gemini = FakeProvider("gemini", [ProviderError("busy"), ProviderError("busy too")])
    claude = FakeProvider("claude", [["Answer."]])
    events = run(Assistant([gemini, claude]), question="what is the capital of France?")

    assert [name for name, _ in events] == ["route", "delta", "done"]
    assert events[0][1]["providers"] == ["gemini", "claude"]
    assert [c.model for c in gemini.calls] == ["m1", "m2"]  # both its models tried first
    assert events[-1][1]["provider"] == "Claude"


def test_a_service_failing_mid_answer_is_reset_and_the_next_starts_over():
    partial = "Half of an answer that the reader has already started to see"
    gemini = FakeProvider("gemini", [[partial, ProviderError("dropped")]], models=["m1"])
    groq = FakeProvider("groq", [["Whole answer."]])
    events = run(Assistant([gemini, groq]), question="what is HMAC?")

    names = [name for name, _ in events]
    assert "reset" in names
    after_reset = names[names.index("reset") + 1 :]
    assert after_reset[-1] == "done"
    assert events[-1][1]["answer"] == "Whole answer."


def test_when_every_service_fails_the_last_reason_is_reported():
    gemini = FakeProvider("gemini", [ProviderError("quota"), ProviderError("Gemini m2: quota")])
    events = run(Assistant([gemini]))
    assert events[-1] == (
        "error",
        {"status": 503, "detail": "Every AI service failed; the last said: Gemini m2: quota"},
    )
    with pytest.raises(AssistantError) as failure:
        Assistant([FakeProvider("gemini", [ProviderError("a"), ProviderError("b")])]).answer(
            "q", []
        )
    assert failure.value.status_code == 503


def test_no_configured_service_is_an_error():
    assert run(Assistant([]))[-1] == (
        "error",
        {"status": 503, "detail": "No AI service is configured; add an API key."},
    )


def test_unrelated_excerpts_are_left_out_and_small_talk_does_not_search_the_web():
    gemini = FakeProvider("gemini", [["Hello!"]], web_search=True)
    events = run(Assistant([gemini], min_score=0.3), question="hello", chunks=[chunk(0.12)])
    assert events[-1][1]["chunks"] == []
    assert gemini.calls[0].turns[-1].content == "hello"
    assert gemini.calls[0].web is False


def test_web_sources_are_returned_once_each():
    page = {"title": "Paris", "url": "https://example.com/paris"}
    gemini = FakeProvider("gemini", [["Paris.", page, page]], web_search=True)
    done = run(Assistant([gemini]), question="what is the capital of France?")[-1][1]
    assert done["web_sources"] == [page]


def test_best_mode_starts_with_the_strongest_service():
    groq = FakeProvider("groq", [["fast"]])
    claude = FakeProvider("claude", [["strong"]])
    assistant = Assistant([groq, claude], best_order="claude,groq")
    assert run(assistant, question="hello", mode="best")[-1][1]["provider"] == "Claude"


def test_an_empty_reply_counts_as_a_failure():
    gemini = FakeProvider("gemini", [[f"{FOLLOW_UPS}\nq?"]], models=["m1"])
    groq = FakeProvider("groq", [["Real answer."]])
    assert run(Assistant([gemini, groq]))[-1][1]["answer"] == "Real answer."


# --- The services' wire formats -------------------------------------------------


class StubStreamingHttp:
    """Stands in for httpx2.Client.stream: one canned (status, lines) per request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    @contextmanager
    def stream(self, method, url, headers, json):
        self.requests.append(SimpleNamespace(method=method, url=url, headers=headers, json=json))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        status, lines = item
        body = "\n".join(lines).encode()
        yield SimpleNamespace(status_code=status, iter_lines=lambda: iter(lines), read=lambda: body)


def sse(*payloads):
    return [f"data: {json.dumps(p) if not isinstance(p, str) else p}" for p in payloads]


def test_gemini_streams_text_skips_thoughts_and_collects_web_sources():
    http = StubStreamingHttp(
        (
            200,
            sse(
                {"candidates": [{"content": {"parts": [{"text": "plan", "thought": True}]}}]},
                {"candidates": [{"content": {"parts": [{"text": "Paris "}]}}]},
                {
                    "candidates": [
                        {
                            "content": {"parts": [{"text": "it is."}]},
                            "finishReason": "MAX_TOKENS",
                            "groundingMetadata": {
                                "groundingChunks": [
                                    {"web": {"uri": "https://x.test", "title": "X"}}
                                ]
                            },
                        }
                    ],
                    "modelVersion": "gemini-3.6-flash",
                },
            ),
        )
    )
    provider = GeminiProvider(http, "key", ["gemini-flash-latest"], 1000)
    outcome = Outcome()
    text = "".join(
        provider.stream(
            "gemini-flash-latest",
            "sys",
            [Turn("assistant", "a"), Turn("user", "q")],
            outcome,
            web=True,
        )
    )

    assert text == "Paris it is."
    assert outcome.model == "gemini-3.6-flash"
    assert outcome.complete is False
    assert outcome.web_sources == [{"title": "X", "url": "https://x.test"}]
    [request] = http.requests
    assert request.url.endswith("/gemini-flash-latest:streamGenerateContent?alt=sse")
    assert request.headers == {"x-goog-api-key": "key"}
    assert request.json["tools"] == [{"google_search": {}}]
    assert [c["role"] for c in request.json["contents"]] == ["model", "user"]
    assert request.json["system_instruction"] == {"parts": [{"text": "sys"}]}


def test_gemini_errors_carry_googles_reason():
    body = [json.dumps({"error": {"message": "This model is currently experiencing high demand."}})]
    provider = GeminiProvider(StubStreamingHttp((503, body)), "key", ["m"], 1000)
    with pytest.raises(ProviderError, match="high demand"):
        list(provider.stream("m", "sys", [Turn("user", "q")], Outcome(), web=False))


def test_openai_compatible_services_stream_deltas_until_done():
    http = StubStreamingHttp(
        (
            200,
            sse(
                {"model": "llama-3.3-70b", "choices": [{"delta": {"role": "assistant"}}]},
                {"choices": [{"delta": {"content": "Hel"}}]},
                {"choices": [{"delta": {"content": "lo."}, "finish_reason": "length"}]},
                "[DONE]",
            ),
        )
    )
    provider = OpenAICompatibleProvider(
        "groq",
        "Groq",
        "https://api.groq.com/openai/v1/",
        http,
        "gsk",
        ["llama"],
        500,
        extra_headers={"X-Title": "Atlas"},
    )
    outcome = Outcome()
    assert (
        "".join(provider.stream("llama", "sys", [Turn("user", "hi")], outcome, web=False))
        == "Hello."
    )
    assert (outcome.model, outcome.complete) == ("llama-3.3-70b", False)

    [request] = http.requests
    assert request.url == "https://api.groq.com/openai/v1/chat/completions"
    assert request.headers == {"Authorization": "Bearer gsk", "X-Title": "Atlas"}
    assert request.json["stream"] is True
    assert request.json["messages"][0] == {"role": "system", "content": "sys"}


def test_openai_compatible_failures_become_provider_errors():
    rejected = StubStreamingHttp((401, [json.dumps({"error": {"message": "Invalid API Key"}})]))
    provider = OpenAICompatibleProvider("groq", "Groq", "https://g", rejected, "k", ["m"], 10)
    with pytest.raises(ProviderError, match="Invalid API Key"):
        list(provider.stream("m", "s", [Turn("user", "q")], Outcome(), web=False))

    request = httpx2.Request("POST", "https://g")
    offline = StubStreamingHttp(httpx2.ConnectError("refused", request=request))
    provider = OpenAICompatibleProvider("groq", "Groq", "https://g", offline, "k", ["m"], 10)
    with pytest.raises(ProviderError, match="could not be reached"):
        list(provider.stream("m", "s", [Turn("user", "q")], Outcome(), web=False))


class StubClaude:
    def __init__(self, pieces=("Hi", "."), stop="end_turn", error=None):
        self.pieces, self.stop, self.error = pieces, stop, error
        self.requests = []
        self.messages = SimpleNamespace(stream=self._stream)

    @contextmanager
    def _stream(self, **kwargs):
        self.requests.append(kwargs)
        if self.error:
            raise self.error
        final = SimpleNamespace(model="claude-opus-5-5", stop_reason=self.stop)
        yield SimpleNamespace(text_stream=iter(self.pieces), get_final_message=lambda: final)


def test_claude_streams_through_the_sdk():
    client = StubClaude()
    outcome = Outcome()
    provider = ClaudeProvider(client, ["claude-opus-5-5"], 2000)
    assert (
        "".join(provider.stream("claude-opus-5-5", "sys", [Turn("user", "q")], outcome, web=False))
        == "Hi."
    )
    assert outcome.model == "claude-opus-5-5"
    assert client.requests[0]["system"] == "sys"
    assert client.requests[0]["messages"] == [{"role": "user", "content": "q"}]


def test_claude_without_credit_is_a_provider_error():
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.BadRequestError(
        "400",
        response=httpx2.Response(400, request=request),
        body={"error": {"message": "Your credit balance is too low."}},
    )
    provider = ClaudeProvider(StubClaude(error=error), ["claude-opus-5-5"], 10)
    with pytest.raises(ProviderError, match="credit balance is too low"):
        list(provider.stream("claude-opus-5-5", "s", [Turn("user", "q")], Outcome(), web=False))


# --- Building it from settings --------------------------------------------------


def test_only_services_with_a_key_are_used(monkeypatch):
    from app.assistant import service
    from app.config import settings

    for key in (
        "gemini_api_key",
        "groq_api_key",
        "openrouter_api_key",
        "mistral_api_key",
        "anthropic_api_key",
    ):
        monkeypatch.setattr(settings, key, None)
    monkeypatch.setattr(settings, "groq_api_key", "gsk")
    monkeypatch.setattr(settings, "mistral_api_key", "ms")
    service._build.cache_clear()
    try:
        assert set(assistant_module.get_assistant().providers) == {"groq", "mistral"}
        monkeypatch.setattr(settings, "groq_api_key", None)
        monkeypatch.setattr(settings, "mistral_api_key", None)
        service._build.cache_clear()
        with pytest.raises(Exception) as missing:
            assistant_module.get_assistant()
        assert missing.value.status_code == 503
    finally:
        service._build.cache_clear()


# --- Through the /ask endpoint --------------------------------------------------


@pytest.fixture
def chat(client):
    """The /ask endpoint with the assistant on stand-in services."""
    from app.assistant import get_assistant
    from app.main import app

    holder = SimpleNamespace(assistant=None)
    app.dependency_overrides[get_assistant] = lambda: holder.assistant
    yield holder
    app.dependency_overrides.pop(get_assistant, None)


def events_of(response):
    events = []
    for block in response.text.split("\n\n"):
        lines = [line for line in block.split("\n") if line and not line.startswith(":")]
        if lines:
            name = lines[0].removeprefix("event: ")
            events.append((name, json.loads(lines[1].removeprefix("data: "))))
    return events


def test_asking_for_a_stream_gets_the_assistant_as_server_sent_events(client, chat, answerer):
    gemini = FakeProvider(
        "gemini", [[f"Title-cased [pkg/models.py:20-21].\n{FOLLOW_UPS}\nA?\nB?\nC?"]]
    )
    chat.assistant = Assistant([gemini])

    response = client.post(
        "/ask",
        json={"question": "format name of a user"},
        headers={"Accept": "text/event-stream"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = events_of(response)
    assert events[0][0] == "route" and events[-1][0] == "done"
    done = events[-1][1]
    assert done["suggestions"] == ["A?", "B?", "C?"]
    assert done["chunks"]  # the knowledge base was searched and shown
    assert answerer.calls == []  # the plain answerer was not used


def test_history_in_json_gets_the_assistant_too(client, chat, answerer):
    groq = FakeProvider("groq", [["Same as before, in Go."]])
    chat.assistant = Assistant([groq])

    response = client.post(
        "/ask",
        json={
            "question": "and in Go?",
            "history": [
                {"role": "user", "content": "format name of a user"},
                {"role": "assistant", "content": "It is title-cased."},
            ],
        },
        headers={"X-Atlas-Mode": "best"},
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "Same as before, in Go."
    sent = groq.calls[0].turns
    assert [t.content for t in sent[:2]] == ["format name of a user", "It is title-cased."]
    assert sent[-1].content.endswith("Question: and in Go?")
    assert answerer.calls == []


def test_a_plain_question_still_gets_the_knowledge_base_answer(client, chat, answerer):
    answerer.reply = "From the code."
    response = client.post("/ask", json={"question": "format name of a user"})
    assert response.json()["answer"] == "From the code."
    assert response.json()["suggestions"] == []
    assert len(answerer.calls) == 1


def test_an_unknown_mode_is_rejected(client, chat):
    chat.assistant = Assistant([FakeProvider("gemini", [["x"]])])
    response = client.post(
        "/ask",
        json={"question": "q", "history": [{"role": "user", "content": "x"}]},
        headers={"X-Atlas-Mode": "fastest"},
    )
    assert response.status_code == 422


def test_assistant_failures_keep_their_status_in_json(client, chat):
    chat.assistant = Assistant([FakeProvider("gemini", [ProviderError("a"), ProviderError("b")])])
    response = client.post(
        "/ask", json={"question": "q", "history": [{"role": "user", "content": "x"}]}
    )
    assert response.status_code == 503
    assert "Every AI service failed" in response.json()["detail"]


def test_gemini_answers_without_search_when_its_search_quota_is_refused():
    quota = [json.dumps({"error": {"message": "You exceeded your current quota."}})]
    answer = sse({"candidates": [{"content": {"parts": [{"text": "From memory."}]}}]})
    http = StubStreamingHttp((429, quota), (200, answer), (200, answer))
    provider = GeminiProvider(http, "key", ["m"], 100)

    text = "".join(provider.stream("m", "s", [Turn("user", "q")], Outcome(), web=True))

    assert text == "From memory."
    assert "tools" in http.requests[0].json and "tools" not in http.requests[1].json
    # Search stays off for a while, so the next question does not try it first.
    assert provider.searches("m") is False
    "".join(provider.stream("m", "s", [Turn("user", "q")], Outcome(), web=True))
    assert len(http.requests) == 3 and "tools" not in http.requests[2].json


def test_recent_events_go_first_to_a_service_that_can_search():
    gemini = FakeProvider("gemini", [["Old news."]], web_search=False)
    groq = FakeProvider("groq", [["Fresh news."]], web_search=True)
    events = run(Assistant([gemini, groq]), question="what is in the news today?")
    assert events[0][1]["providers"] == ["groq", "gemini"]
    assert events[-1][1]["answer"] == "Fresh news."
    assert groq.calls[0].web is True


def test_groq_compound_models_count_as_searching():
    provider = OpenAICompatibleProvider("groq", "Groq", "https://g", None, "k", [], 10)
    assert provider.searches("groq/compound") is True
    assert provider.searches("llama-3.3-70b-versatile") is False
    assert model_order(["llama", "groq/compound"], "current") == ["groq/compound", "llama"]


def test_a_blank_model_list_means_the_defaults(monkeypatch):
    from app.assistant import service
    from app.config import settings

    for key in ("groq_api_key", "openrouter_api_key", "mistral_api_key", "anthropic_api_key"):
        monkeypatch.setattr(settings, key, None)
    monkeypatch.setattr(settings, "gemini_api_key", "key")
    monkeypatch.setattr(settings, "gemini_models", " ")  # docker-compose passes unset as ""
    service._build.cache_clear()
    try:
        assert service._build().providers["gemini"].models == [
            "gemini-flash-latest",
            "gemini-3.5-flash",
            "gemini-flash-lite-latest",
        ]
    finally:
        service._build.cache_clear()
