"""An OpenAI-compatible API, so any OpenAI client can use Atlas as a drop-in: point its
base URL at the server's /v1 and use the model `atlas` (or `atlas-open`)."""

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.embedding import Embedder, get_embedder
from app.ratelimit import rate_limit
from app.routers.search import ask
from app.schemas import AskRequest, ChatCompletionRequest, ChatTurn

router = APIRouter(tags=["openai"])

MODELS = {
    "atlas": "Grounded: answers only from the knowledge base, with citations.",
    "atlas-open": "Also answers from the web and general knowledge.",
}
# What an answer's `atlas` field carries beside the text.
EXTRAS = ("epistemic", "confidence", "mode", "footer", "citations", "grounded", "latency_ms")


def bearer_key(request: Request) -> None:
    """OpenAI clients send their key as `Authorization: Bearer`; an Atlas API key (atl_…)
    sent that way counts as X-Atlas-Key. Any other bearer value is ignored, so a client
    that insists on some key still works without one."""
    supplied = request.headers.get("authorization", "")
    if supplied.lower().startswith("bearer atl_") and "x-atlas-key" not in request.headers:
        request.scope["headers"] = [
            *request.scope["headers"],
            (b"x-atlas-key", supplied[7:].strip().encode()),
        ]
        request.__dict__.pop("_headers", None)  # Starlette caches the parsed headers


@router.get("/v1/models", summary="OpenAI-compatible: the models")
def list_models() -> dict:
    return {
        "object": "list",
        "data": [
            {"id": name, "object": "model", "created": 0, "owned_by": "atlas", "description": text}
            for name, text in MODELS.items()
        ],
    }


@router.post(
    "/v1/chat/completions",
    summary="OpenAI-compatible: a chat completion",
    responses={
        200: {
            "description": "A `chat.completion`, or with `stream: true` server-sent "
            "`chat.completion.chunk`s ending with `data: [DONE]`.",
            "content": {"text/event-stream": {}},
        },
        400: {"description": "The request can't be processed."},
    },
    dependencies=[
        Depends(bearer_key),
        Depends(rate_limit("ask", lambda: settings.ask_rate_limit_per_minute)),
    ],
)
async def chat_completions(
    body: ChatCompletionRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    embedder: Annotated[Embedder, Depends(get_embedder)],
):
    """The last user message is the question and the earlier ones the conversation;
    system (and developer) messages become standing instructions. The answer is Atlas's,
    as on the site: grounded (model `atlas`) with `[path:start-end]` citations, ending with
    its footer line, `[confidence: …] [sources: …] [latency: …]`. The response's `atlas`
    field adds the epistemic state, confidence, mode and checked citations."""
    try:
        asked = _ask_request(body)
    except (ValueError, ValidationError) as error:
        return _error(422, str(error).split("\n")[0])
    headers = [
        (k, v)
        for k, v in request.scope["headers"]
        if k not in (b"accept", b"x-atlas-open", b"content-length")
    ]
    headers.append((b"accept", b"text/event-stream"))
    if body.model == "atlas-open":
        headers.append((b"x-atlas-open", b"true"))
    inner = Request({**request.scope, "headers": headers}, request.receive)
    try:
        response = await run_in_threadpool(
            ask, asked, inner, db, embedder, mode="auto", fresh=False, chat=None
        )
    except HTTPException as error:
        return _error(error.status_code, str(error.detail))
    events = _events(response)
    stamp = int(time.time())
    completion = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    if body.stream:
        return StreamingResponse(
            _chunks(events, completion, stamp, body.model),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    done: dict = {}
    async for name, data in events:
        if name == "done":
            done = data
        elif name == "error":
            return _error(int(data.get("status") or 502), str(data.get("detail") or "failed"))
    return {
        "id": completion,
        "object": "chat.completion",
        "created": stamp,
        "model": body.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": _content(done)},
                "finish_reason": "stop" if done.get("complete", True) else "length",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "atlas": {k: done.get(k) for k in EXTRAS},
    }


def _ask_request(body: ChatCompletionRequest) -> AskRequest:
    """The /ask request for an OpenAI conversation."""
    last = body.messages[-1]
    if last.role != "user" or not last.text().strip():
        raise ValueError("The last message must be the user's question.")
    instructions = "\n\n".join(
        m.text().strip() for m in body.messages if m.role in ("system", "developer")
    ).strip()
    history = [
        ChatTurn(role=m.role, content=m.text()[:60000])
        for m in body.messages[:-1]
        if m.role in ("user", "assistant") and m.text().strip()
    ][-40:]
    return AskRequest(
        question=last.text().strip()[:8000],
        history=history,
        instructions=instructions[:4000],
        temperature=body.temperature,
    )


def _content(data: dict) -> str:
    """The answer, ending with its footer."""
    answer = (data.get("answer") or "").rstrip()
    footer = data.get("footer")
    return f"{answer}\n\n{footer}" if footer else answer


async def _events(response) -> AsyncIterator[tuple[str, dict]]:
    """The events of /ask's stream (or its one answer, if it gave one)."""
    if not isinstance(response, StreamingResponse):
        data = response.model_dump() if hasattr(response, "model_dump") else dict(response)
        yield "done", data
        return
    buffer = ""
    async for piece in response.body_iterator:
        buffer += piece if isinstance(piece, str) else piece.decode()
        while "\n\n" in buffer:
            block, buffer = buffer.split("\n\n", 1)
            if block.startswith(":"):
                yield "keep-alive", {}
                continue
            name, data = "message", ""
            for line in block.split("\n"):
                if line.startswith("event:"):
                    name = line[6:].strip()
                elif line.startswith("data:"):
                    data += line[5:].strip()
            try:
                yield name, json.loads(data) if data else {}
            except ValueError:
                continue


async def _chunks(
    events: AsyncIterator[tuple[str, dict]], completion: str, stamp: int, model: str
) -> AsyncIterator[str]:
    def chunk(delta: dict, finish: str | None = None, extra: dict | None = None) -> str:
        data = {
            "id": completion,
            "object": "chat.completion.chunk",
            "created": stamp,
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        if extra is not None:
            data["atlas"] = extra
        return f"data: {json.dumps(data)}\n\n"

    yield chunk({"role": "assistant", "content": ""})
    sent = ""
    async for name, data in events:
        if name == "keep-alive":
            yield ": keep-alive\n\n"
        elif name == "delta" and data.get("text"):
            sent += data["text"]
            yield chunk({"content": data["text"]})
        elif name == "reset" and sent:
            # Another model took over: OpenAI's stream cannot take text back, so mark it.
            sent = ""
            yield chunk({"content": "\n\n---\n\n"})
        elif name == "done":
            final = _content(data)
            rest = (
                final[len(sent) :]
                if final.startswith(sent)
                else "\n\n" + (data.get("footer") or "")
            )
            if rest.strip():
                yield chunk({"content": rest})
            yield chunk({}, "stop", {k: data.get(k) for k in EXTRAS})
        elif name == "error":
            yield chunk({"content": f"\n\n[error: {data.get('detail') or 'the answer failed'}]"})
            yield chunk({}, "stop")
    yield "data: [DONE]\n\n"


def _error(status: int, message: str) -> JSONResponse:
    kind = "invalid_request_error" if 400 <= status < 500 else "api_error"
    return JSONResponse(
        {"error": {"message": message, "type": kind, "code": status}}, status_code=status
    )
