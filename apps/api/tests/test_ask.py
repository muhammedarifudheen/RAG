from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from fastapi import HTTPException

from app import llm
from app.config import settings
from app.llm import SYSTEM_PROMPT, AnswerError, ClaudeAnswerer
from app.schemas import CodeChunk

QUESTION = "format name of a user"


def test_answer_carries_citations_and_the_code_chunks(client, answerer):
    answerer.reply = (
        "Names are stripped and title-cased [pkg/models.py:20-21]. "
        "They are stored elsewhere [pkg/nope.py:1-2], see again [pkg/models.py:20-21]."
    )

    response = client.post("/ask", json={"question": QUESTION, "top_k": 3})

    assert response.status_code == 200
    body = response.json()
    assert body["question"] == QUESTION
    assert body["answer"] == answerer.reply
    assert body["model"] == "fake-model"
    assert body["complete"] is True

    # Repeated citations are listed once; one pointing at code the model never saw is flagged.
    assert body["citations"] == [
        {
            "ref": "[pkg/models.py:20-21]",
            "file": "pkg/models.py",
            "start_line": 20,
            "end_line": 21,
            "verified": True,
        },
        {
            "ref": "[pkg/nope.py:1-2]",
            "file": "pkg/nope.py",
            "start_line": 1,
            "end_line": 2,
            "verified": False,
        },
    ]

    assert len(body["chunks"]) == 3
    format_name = next(c for c in body["chunks"] if c["name"] == "format_name")
    assert format_name["snippet"].startswith("def format_name(name: str) -> str:")
    assert all(chunk["snippet"] for chunk in body["chunks"])


def test_the_model_receives_the_question_and_the_search_results(client, answerer):
    body = client.post("/ask", json={"question": f"  {QUESTION}  ", "top_k": 4}).json()

    [(question, chunks)] = answerer.calls
    assert question == QUESTION
    assert [c.symbol_id for c in chunks] == [c["symbol_id"] for c in body["chunks"]]
    assert len(chunks) == 4
    # Same ranking as /search.
    searched = client.get("/search", params={"q": QUESTION, "limit": 4}).json()["results"]
    assert [c["symbol_id"] for c in searched] == [c.symbol_id for c in chunks]


def test_top_k_defaults_to_8(client, answerer):
    client.post("/ask", json={"question": QUESTION})
    assert len(answerer.calls[0][1]) == 8


def test_citations_must_fall_inside_a_chunks_lines(client, answerer):
    answerer.reply = "Wide [pkg/models.py:1-200], narrow [pkg/models.py:21-21], bare [pkg/models.py:20]."

    citations = client.post("/ask", json={"question": QUESTION, "top_k": 1}).json()["citations"]

    assert [(c["ref"], c["verified"]) for c in citations] == [
        ("[pkg/models.py:1-200]", False),
        ("[pkg/models.py:21-21]", True),
        ("[pkg/models.py:20]", True),
    ]


def test_a_citation_with_several_ranges_is_checked_range_by_range(client, answerer):
    # Models sometimes cite two places in one file within a single bracket.
    answerer.reply = "Formatting happens here [pkg/models.py:20-20, 21-21, 1-200]."

    citations = client.post("/ask", json={"question": QUESTION, "top_k": 1}).json()["citations"]

    assert [(c["ref"], c["start_line"], c["end_line"], c["verified"]) for c in citations] == [
        ("[pkg/models.py:20-20]", 20, 20, True),
        ("[pkg/models.py:21-21]", 21, 21, True),
        ("[pkg/models.py:1-200]", 1, 200, False),
    ]


def test_a_range_across_two_shown_excerpts_is_verified(client, answerer):
    # With top_k=8, models.py is shown as several excerpts: User.label (16-17) and
    # format_name (20-21) among them, but not lines 18-19 in between.
    answerer.reply = "Across [pkg/models.py:16-17] and [pkg/models.py:20-21]; not [pkg/models.py:16-21]."

    body = client.post("/ask", json={"question": "user label format name", "top_k": 8}).json()
    shown = {(c["file"], c["start_line"], c["snippet_end_line"]) for c in body["chunks"]}
    assert ("pkg/models.py", 16, 17) in shown and ("pkg/models.py", 20, 21) in shown
    lines_18_19_shown = any(
        f == "pkg/models.py" and s <= 18 and e >= 19 for f, s, e in shown
    )

    verified = {c["ref"]: c["verified"] for c in body["citations"]}
    assert verified["[pkg/models.py:16-17]"] is True
    assert verified["[pkg/models.py:20-21]"] is True
    # 16-21 is verified only if 18-19 were shown too, by the module or class excerpt.
    assert verified["[pkg/models.py:16-21]"] is lines_18_19_shown


def test_backwards_ranges_are_not_verified(client, answerer):
    answerer.reply = "Backwards [pkg/models.py:21-20]."
    citations = client.post("/ask", json={"question": QUESTION, "top_k": 1}).json()["citations"]
    assert [(c["ref"], c["verified"]) for c in citations] == [("[pkg/models.py:21-20]", False)]


def test_model_failures_keep_their_status(client, answerer):
    answerer.error = AnswerError(502, "The Anthropic API could not be reached.")

    response = client.post("/ask", json={"question": QUESTION})

    assert response.status_code == 502
    assert response.json() == {"detail": "The Anthropic API could not be reached."}


def test_invalid_requests_are_rejected_before_the_model_is_called(client, answerer):
    assert client.post("/ask", json={}).status_code == 422
    assert client.post("/ask", json={"question": "   "}).status_code == 422
    assert client.post("/ask", json={"question": "x", "top_k": 0}).status_code == 422
    assert client.post("/ask", json={"question": "x", "top_k": 21}).status_code == 422
    assert answerer.calls == []


def test_ask_has_its_own_lower_rate_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "ask_rate_limit_per_minute", 2)

    statuses = [client.post("/ask", json={"question": QUESTION}).status_code for _ in range(3)]

    assert statuses == [200, 200, 429]
    assert client.get("/search", params={"q": "user"}).status_code == 200


# --- ClaudeAnswerer, against a stand-in for the Anthropic client ---------------

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


class StubClient:
    def __init__(self, stop_reason: str = "end_turn", error: Exception | None = None) -> None:
        self.requests: list[dict] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))
        self._stop_reason = stop_reason
        self._error = error

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        if self._error is not None:
            raise self._error
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="thinking", thinking=""),
                SimpleNamespace(type="text", text="  Title-cased [pkg/models.py:21-21].\n"),
            ],
            stop_reason=self._stop_reason,
            model="claude-opus-5-5",
        )


def make_answerer(client: StubClient) -> ClaudeAnswerer:
    return ClaudeAnswerer(client, "claude-opus-5-5", "medium", 16000)


def test_claude_request_contains_numbered_excerpts_then_the_question():
    stub = StubClient()

    result = make_answerer(stub).answer("How are names formatted?", [CHUNK])

    assert result.text == "Title-cased [pkg/models.py:21-21]."
    assert result.model == "claude-opus-5-5"
    assert result.complete is True

    [request] = stub.requests
    assert request["model"] == "claude-opus-5-5"
    assert request["max_tokens"] == 16000
    assert request["system"] == SYSTEM_PROMPT
    assert request["output_config"] == {"effort": "medium"}
    assert request["fallbacks"] == "default"
    assert request["betas"] == ["server-side-fallback-2026-07-01"]
    assert "thinking" not in request and "temperature" not in request
    [message] = request["messages"]
    assert message["role"] == "user"
    assert message["content"] == (
        "<excerpts>\n"
        '<excerpt path="pkg/models.py" lines="20-21" symbol="format_name" kind="function">\n'
        "20| def format_name(name: str) -> str:\n"
        "21|     return name.strip().title()\n"
        "</excerpt>\n"
        "</excerpts>\n\n"
        "Question: How are names formatted?"
    )


def test_claude_refusal_and_truncation_are_reported():
    with pytest.raises(AnswerError) as refused:
        make_answerer(StubClient(stop_reason="refusal")).answer("q", [CHUNK])
    assert refused.value.status_code == 422

    cut_off = make_answerer(StubClient(stop_reason="max_tokens")).answer("q", [CHUNK])
    assert cut_off.complete is False


@pytest.mark.parametrize(
    ("credentials", "configured"),
    [
        ({"api_key": None, "auth_token": None, "credentials": None}, False),
        ({"api_key": "sk-test", "auth_token": None, "credentials": None}, True),
        ({"api_key": None, "auth_token": None, "credentials": object()}, True),
    ],
)
def test_missing_credentials_are_a_503_before_any_request(monkeypatch, credentials, configured):
    answerer = ClaudeAnswerer(SimpleNamespace(**credentials), "claude-opus-5-5", "medium", 16000)
    monkeypatch.setattr(llm, "_claude", lambda: answerer)

    if configured:
        assert llm.get_answerer() is answerer
    else:
        with pytest.raises(HTTPException) as missing:
            llm.get_answerer()
        assert missing.value.status_code == 503
        assert "ANTHROPIC_API_KEY" in missing.value.detail


def test_claude_bad_request_passes_on_anthropics_reason():
    # Anthropic answers 400 when the account has no credit; the user needs to see why.
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    reason = "Your credit balance is too low to access the Anthropic API."
    error = anthropic.BadRequestError(
        "Error code: 400",
        response=httpx2.Response(400, request=request),
        body={"type": "error", "error": {"type": "invalid_request_error", "message": reason}},
    )

    with pytest.raises(AnswerError) as failure:
        make_answerer(StubClient(error=error)).answer("q", [CHUNK])

    assert failure.value.status_code == 502
    assert failure.value.detail == f"Anthropic rejected the request: {reason}"


def test_claude_connection_failure_becomes_a_502():
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    stub = StubClient(error=anthropic.APIConnectionError(request=request))

    with pytest.raises(AnswerError) as failure:
        make_answerer(stub).answer("q", [CHUNK])

    assert failure.value.status_code == 502
