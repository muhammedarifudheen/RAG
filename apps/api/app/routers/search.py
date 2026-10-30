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
from app.assistant.agent import ResearchTools
from app.assistant.gaps import suggested_source
from app.assistant.planner import fuse
from app.assistant.rerank import rerank
from app.assistant.router import wants_research
from app.config import settings
from app.db import get_db
from app.embedding import Embedder, get_embedder
from app.llm import Answerer, AnswerError, get_answerer
from app.ratelimit import rate_limit
from app.schemas import AskRequest, AskResponse, GapReport, Reranking, SearchResponse
from app.services.catalog import source_catalog
from app.services.search import extract_citations, search_symbols
from app.services.spans import read_span

# How long to wait for the ranker once the judge is done (it has its own time limit).
RANK_WAIT = 10.0

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

    if body.task == "check":
        # A fact-check of an answer already given, against the excerpts it was given.
        if not (body.answer or "").strip():
            raise HTTPException(422, "answer must be given to check it.")
        checker: Assistant = _resolve(request, get_assistant)
        report = checker.fact_check(question, body.answer, body.chunks, body.attachments)
        if report is None:
            raise HTTPException(503, "The fact-checker is busy; try again in a minute.")
        return AskResponse(
            question=question,
            answer=body.answer,
            citations=extract_citations(body.answer, body.chunks),
            chunks=body.chunks,
            model=report.checked_by,
            complete=True,
            fact_check=report,
        )

    if body.task == "gaps":
        # What the knowledge base would need to answer the question.
        finder: Assistant = _resolve(request, get_assistant)
        found = finder.find_gaps(question, source_catalog(db))
        if found is None:
            raise HTTPException(503, "The gap finder is busy; try again in a minute.")
        report, found_by = found
        return AskResponse(
            question=question,
            answer=report,
            citations=[],
            chunks=[],
            model=found_by,
            complete=True,
            gaps=GapReport(
                report=report, suggestion_url=suggested_source(report), found_by=found_by
            ),
        )

    streaming = "text/event-stream" in request.headers.get("accept", "")
    if streaming or body.for_assistant:
        assistant: Assistant = _resolve(request, get_assistant)
        # A follow-up such as "and in Go?" finds little on its own; search with the
        # previous question too.
        previous = next((t.content for t in reversed(body.history) if t.role == "user"), "")
        query = f"{previous[:500]}\n{question}" if previous else question
        queries = [query]
        research = body.use_sources and (
            body.research
            if body.research is not None
            else settings.assistant_research_auto and wants_research(question)
        )
        # Researching, the agent plans its own searches and reads what it needs: no
        # planner or judge.
        planning = body.use_sources and body.plan_queries and getattr(assistant, "planner", False)
        if planning and not research:
            queries = assistant.plan_queries(query)
        judging = (
            not research
            and body.use_sources
            and body.rerank
            and getattr(assistant, "reranker", False)
        )
        # The judge picks from a few more excerpts than are shown.
        pool = min(body.top_k + 4, 20) if judging else body.top_k
        chunks = (
            fuse(
                [
                    search_symbols(db, embedder, q, pool, settings.snippet_max_lines)
                    for q in queries
                ],
                pool,
            )
            if body.use_sources
            else []
        )
        reranking = None
        if judging and chunks:
            cutoff = (
                settings.assistant_rerank_cutoff
                if body.rerank_cutoff is None
                else body.rerank_cutoff
            )
            candidates = list(chunks)
            # The ranker orders every candidate while the judge scores them, so the two
            # take as long as the slower; its order is then applied to those kept.
            ranked: queue.Queue = queue.Queue()
            if body.rank_passages:
                threading.Thread(
                    target=lambda: ranked.put(assistant.rank_chunks(query, candidates)),
                    daemon=True,
                ).start()
            verdicts = assistant.judge_chunks(query, candidates)
            chunks = rerank(candidates, verdicts, cutoff, body.top_k)
            ranking = None
            if body.rank_passages:
                try:
                    ranking = ranked.get(timeout=RANK_WAIT)
                except queue.Empty:
                    ranking = None
            applied = ranking is not None and len(chunks) >= 2
            if applied:
                place = {candidates[i].symbol_id: p for p, i in enumerate(ranking[0])}
                chunks.sort(key=lambda c: place.get(c.symbol_id, len(place)))
            first = candidates[ranking[0][0]].symbol_id if ranking else None
            reranking = Reranking(
                candidates=len(candidates),
                judged=len(verdicts),
                kept=len(chunks),
                cutoff=cutoff,
                ranked=applied,
                # Its reason, when its first choice is one the judge kept.
                top_pick=(ranking[1] or None)
                if applied and any(c.symbol_id == first for c in chunks)
                else None,
            )
        options = Options(
            attachments=body.attachments,
            style=body.style,
            temperature=body.temperature,
            instructions=body.instructions,
            task=body.task,
            services=tuple(body.services),
            council_size=body.council_size,
            merger=body.merger,
            min_score=body.min_score,
            web_search=body.web_search,
            max_tokens=body.max_tokens,
            format=body.format,
            include_drafts=body.include_drafts,
            strict=body.strict,
            search_queries=tuple(queries) if len(queries) > 1 else (),
            reranking=reranking,
            research=ResearchTools(
                search=lambda q: search_symbols(db, embedder, q, 6, settings.snippet_max_lines),
                read=lambda path, start, end: read_span(db, path, start, end),
            )
            if research
            else None,
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
