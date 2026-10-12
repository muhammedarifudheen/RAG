from types import SimpleNamespace

import httpx2
import pytest
from fastapi import HTTPException

from app import llm
from app.config import settings
from app.llm import GEMINI_URL, SYSTEM_PROMPT, AnswerError, GeminiAnswerer
from app.schemas import CodeChunk

CHUNK = CodeChunk(
    symbol_id=7,
    name="format_name",
    kind="function",
    signature="def format_name(name: str) -> str",
    file="pkg/models.py",
    language="python",
    start_line=20,
    end_line=21,
    score=0.9,
    snippet="def format_name(name: str) -> str:\n    return name.strip().title()",
    snippet_end_line=21,
    truncated=False,
    citation="[pkg/models.py:20-21]",
)


def reply(text="Title-cased [pkg/models.py:21-21].", finish="STOP", version="gemini-3.6-flash"):
    return 200, {
        "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish}],
        "modelVersion": version,
    }


def error(status, message):
    return status, {"error": {"code": status, "message": message}}


class StubHttp:
    """Stands in for httpx2.Client: answers each POST with the next canned response."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[SimpleNamespace] = []

    def post(self, url, headers, json):
        self.requests.append(SimpleNamespace(url=url, headers=headers, json=json))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        status, body = item
        return httpx2.Response(status, json=body, request=httpx2.Request("POST", url))


def make(http, models=("first", "second")):
    return GeminiAnswerer(http, "test-key", models, max_tokens=4096, pause=0)


def test_request_carries_the_system_prompt_the_excerpts_and_the_key():
    http = StubHttp(reply())

    result = make(http).answer("How are names formatted?", [CHUNK])

    assert result.text == "Title-cased [pkg/models.py:21-21]."
    assert result.model == "gemini-3.6-flash"  # the model that served it, not the alias asked for
    assert result.complete is True

    [request] = http.requests
    assert request.url == GEMINI_URL.format(model="first")
    assert request.headers == {"x-goog-api-key": "test-key"}
    assert "test-key" not in request.url
    assert request.json["system_instruction"] == {"parts": [{"text": SYSTEM_PROMPT}]}
    assert request.json["generationConfig"] == {"maxOutputTokens": 4096}
    [content] = request.json["contents"]
    assert content["role"] == "user"
    prompt = content["parts"][0]["text"]
    assert '<excerpt path="pkg/models.py" lines="20-21"' in prompt
    assert "20| def format_name(name: str) -> str:" in prompt
    assert prompt.endswith("Question: How are names formatted?")


@pytest.mark.parametrize("status", [429, 500, 503])
def test_an_overloaded_model_falls_through_to_the_next(status):
    http = StubHttp(error(status, "This model is currently experiencing high demand."), reply())

    result = make(http).answer("q", [CHUNK])

    assert result.text.startswith("Title-cased")
    assert [r.url for r in http.requests] == [
        GEMINI_URL.format(model="first"),
        GEMINI_URL.format(model="second"),
    ]


def test_models_are_retried_in_a_second_pass_before_giving_up():
    busy = error(503, "high demand")
    http = StubHttp(busy, busy, busy, reply())

    assert make(http).answer("q", [CHUNK]).complete is True
    assert len(http.requests) == 4


def test_when_every_model_is_unavailable_the_reason_is_reported():
    busy = error(503, "This model is currently experiencing high demand.")
    http = StubHttp(busy, busy, busy, busy)

    with pytest.raises(AnswerError) as failure:
        make(http).answer("q", [CHUNK])

    assert failure.value.status_code == 503
    assert failure.value.detail == (
        "Gemini is unavailable: This model is currently experiencing high demand."
    )


def test_network_failures_and_empty_answers_also_move_on():
    request = httpx2.Request("POST", "https://example.invalid")
    empty = (200, {"candidates": [{"content": {"parts": []}, "finishReason": "STOP"}]})
    http = StubHttp(httpx2.ConnectError("refused", request=request), empty, reply())

    assert make(http).answer("q", [CHUNK]).text.startswith("Title-cased")
    assert len(http.requests) == 3


def test_a_rejected_key_fails_at_once_without_trying_other_models():
    http = StubHttp(error(403, "API key not valid."))

    with pytest.raises(AnswerError) as failure:
        make(http).answer("q", [CHUNK])

    assert failure.value.status_code == 503
    assert failure.value.detail == "The Gemini API key was rejected: API key not valid."
    assert len(http.requests) == 1


def test_other_client_errors_pass_on_googles_reason():
    http = StubHttp(error(400, "Invalid JSON payload received."))

    with pytest.raises(AnswerError) as failure:
        make(http).answer("q", [CHUNK])

    assert failure.value.status_code == 502
    assert failure.value.detail == "Gemini rejected the request: Invalid JSON payload received."


@pytest.mark.parametrize(
    "body",
    [
        {"promptFeedback": {"blockReason": "SAFETY"}},
        {"candidates": [{"finishReason": "SAFETY"}]},
    ],
)
def test_a_declined_answer_is_a_422(body):
    with pytest.raises(AnswerError) as failure:
        make(StubHttp((200, body))).answer("q", [CHUNK])
    assert failure.value.status_code == 422


def test_truncation_and_thought_parts():
    cut_off = make(StubHttp(reply(finish="MAX_TOKENS"))).answer("q", [CHUNK])
    assert cut_off.complete is False

    thinking = (
        200,
        {
            "candidates": [
                {
                    "content": {"parts": [{"text": "planning", "thought": True}, {"text": "Answer."}]},
                    "finishReason": "STOP",
                }
            ]
        },
    )
    assert make(StubHttp(thinking)).answer("q", [CHUNK]).text == "Answer."


def test_provider_setting_selects_gemini(monkeypatch):
    answerer = make(StubHttp())
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(llm, "_gemini", lambda: answerer)

    assert llm.get_answerer() is answerer


def test_gemini_without_a_key_is_a_503(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "")

    with pytest.raises(HTTPException) as missing:
        llm.get_answerer()

    assert missing.value.status_code == 503
    assert "GEMINI_API_KEY" in missing.value.detail


def test_blank_model_list_falls_back_to_the_defaults(monkeypatch):
    monkeypatch.setattr(settings, "gemini_models", " , ")
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    llm._gemini.cache_clear()
    try:
        assert llm._gemini().models == list(llm.DEFAULT_GEMINI_MODELS)
    finally:
        llm._gemini.cache_clear()
