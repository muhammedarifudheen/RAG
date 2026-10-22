import json
import logging
import queue
import threading
from collections.abc import Callable, Iterator
from typing import Annotated, Literal, TypeVar

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.assistant import Assistant, AssistantError, Options, get_assistant
from app.config import settings
from app.db import get_db
from app.embedding import Embedder, get_embedder
from app.llm import Answerer, AnswerError, get_answerer
from app.ratelimit import rate_limit
from app.schemas import AskRequest, AskResponse, SearchResponse
from app.services.search import extract_citations, search_symbols

RATE_LIMITED = {429: {"description": "Rate limit exceeded; see the Retry-After header."}}

router = APIRouter(tags=["search"])
logger = logging.getLogger("atlas.api.ask")
T = TypeVar("T")


@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Semantic search over the knowledge base",
    responses=RATE_LIMITED,
    dependencies=[Depends(rate_limit("default", lambda: settings.rate_limit_per_minute))],
)
def search(
    q: Annotated[
        str,
        Query(min_length=1, max_length=1000, description="Natural-language query."),
    ],
    db: Annotated[Session, Depends(get_db)],
    embedder: Annotated[Embedder, Depends(get_embedder)],
    limit: Annotated[int, Query(ge=1, le=50, description="Maximum results.")] = 20,
) -> SearchResponse:
    """Embeds the query and returns the symbols with the most similar embeddings,
    nearest first, each with its file path, line range and source snippet."""
    query = q.strip()
    if not query:
        raise HTTPException(422, "q must not be blank.")
    results = search_symbols(db, embedder, query, limit, settings.snippet_max_lines)
    return SearchResponse(query=query, results=results)


@router.post(
    "/ask",
    response_model=AskResponse,
    summary="Ask a question about the knowledge base",
    responses={
        **RATE_LIMITED,
        200: {
            "description": "The answer. With `Accept: text/event-stream`, a stream of events "
            "instead: `route`, then `delta` pieces of the answer (`reset` drops the text so far "
            "when the assistant moves to another model), then `done` with this same body, or "
            "`error`.",
            "content": {"text/event-stream": {}},
        },
        409: {"description": "Nothing has been ingested yet (plain questions only)."},
        422: {"description": "Invalid request, or the model declined to answer."},
        502: {"description": "The model provider (Anthropic or Gemini) failed."},
        503: {
            "description": "The model provider is not configured, rejected the key, or is rate limiting."
        },
    },
    dependencies=[Depends(rate_limit("ask", lambda: settings.ask_rate_limit_per_minute))],
)
def ask(
    body: AskRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    embedder: Annotated[Embedder, Depends(get_embedder)],
    mode: Annotated[
        Literal["auto", "best"],
        Header(
            alias="X-Atlas-Mode",
            description="Assistant only: route by question type "
            "(`auto`) or start with the strongest model (`best`).",
        ),
    ] = "auto",
):
    """Two ways to ask.

    **A plain question** (JSON, no `history`): runs the same vector search as `/search`,
    sends the top results and the question to the configured model (Claude or Gemini),
    and returns the answer with inline `[path:start-end]` citations, from the knowledge
    base only. `chunks` holds the excerpts sent to the model; each citation is `verified`
    only if its lines lie inside one of them.

    **The assistant** (`Accept: text/event-stream`, or any of `history`, `attachments`,
    `style`, `temperature`, `instructions` or `task`): answers anything, from the knowledge
    base (cited the same way), attached files and images, a web search, or general
    knowledge. It picks the model by question type (or the strongest, with
    `X-Atlas-Mode: best`), falls back to the next when one fails, remembers the
    conversation and suggests follow-ups. With `task: image`, or a request such as "draw a
    lighthouse", it draws a picture instead: `images` holds its address."""
    question = body.question.strip()
    if not question:
        raise HTTPException(422, "question must not be blank.")

    streaming = "text/event-stream" in request.headers.get("accept", "")
    if streaming or body.for_assistant:
        assistant: Assistant = _resolve(request, get_assistant)
        # A follow-up such as "and in Go?" finds little on its own; search with the
        # previous question too.
        previous = next((t.content for t in reversed(body.history) if t.role == "user"), "")
        query = f"{previous[:500]}\n{question}" if previous else question
        chunks = search_symbols(db, embedder, query, body.top_k, settings.snippet_max_lines)
        options = Options(
            attachments=body.attachments,
            style=body.style,
            temperature=body.temperature,
            instructions=body.instructions,
            task=body.task,
        )
        if streaming:
            events = assistant.respond(question, chunks, body.history, mode, options)
            return StreamingResponse(
                _event_stream(events),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        try:
            return assistant.answer(question, chunks, body.history, mode, options)
        except AssistantError as error:
            raise HTTPException(error.status_code, error.detail) from error

    answerer: Answerer = _resolve(request, get_answerer)
    chunks = search_symbols(db, embedder, question, body.top_k, settings.snippet_max_lines)
    if not chunks:
        raise HTTPException(409, "The knowledge base is empty; add a source first.")

    try:
        result = answerer.answer(question, chunks)
    except AnswerError as error:
        raise HTTPException(error.status_code, error.detail) from error

    return AskResponse(
        question=question,
        answer=result.text,
        citations=extract_citations(result.text, chunks),
        chunks=chunks,
        model=result.model,
        complete=result.complete,
    )


def _resolve(request: Request, dependency: Callable[[], T]) -> T:
    """Resolves a dependency only on the path that needs it, honouring overrides."""
    return request.app.dependency_overrides.get(dependency, dependency)()


KEEP_ALIVE_SECONDS = 15.0


def _event_stream(events: Iterator[tuple[str, dict]]) -> Iterator[str]:
    """Server-sent events from the assistant, with a comment every 15 s while a model
    thinks, so proxies do not close a quiet connection."""
    pending: queue.Queue = queue.Queue()
    end = object()

    def run() -> None:
        try:
            for event in events:
                pending.put(event)
        except Exception:  # never leave the browser waiting for an answer
            logger.exception("The assistant failed")
            pending.put(("error", {"status": 500, "detail": "The assistant failed unexpectedly."}))
        finally:
            pending.put(end)

    threading.Thread(target=run, daemon=True).start()
    while True:
        try:
            item = pending.get(timeout=KEEP_ALIVE_SECONDS)
        except queue.Empty:
            yield ": keep-alive\n\n"
            continue
        if item is end:
            return
        name, data = item
        yield f"event: {name}\ndata: {json.dumps(data)}\n\n"
