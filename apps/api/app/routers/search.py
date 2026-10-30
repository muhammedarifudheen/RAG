import json
import logging
import queue
import threading
import time
from collections.abc import Callable, Iterator
from typing import Annotated, Literal, TypeVar

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.assistant import Assistant, AssistantError, Options, cache, get_assistant
from app.assistant.agent import ResearchTools
from app.assistant.gaps import suggested_source
from app.assistant.planner import fuse
from app.assistant.rerank import rerank
from app.assistant.router import wants_research
from app.config import settings
from app.db import get_db
from app.embedding import Embedder, get_embedder
from app.llm import Answerer, AnswerError, get_answerer
from app.models import Source
from app.ratelimit import rate_limit
from app.schemas import AskRequest, AskResponse, GapReport, Reranking, SearchResponse
from app.services.catalog import source_catalog
from app.services.search import extract_citations, hybrid_search, search_symbols
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
    fresh: Annotated[
        bool,
        Header(
            alias="X-Atlas-Fresh",
            description="Assistant only: true answers afresh rather than reusing the answer "
            "to the same question (Regenerate sends it); the new answer is still kept.",
        ),
    ] = False,
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

    # A repeated question within a day: the answer given before.
    answers, cache_key = None, None
    if streaming_or_assistant(body, request) and body.task == "answer":
        answers = getattr(_resolve(request, get_assistant), "answer_cache", None)
        cache_key = _cache_key(body, mode, db) if answers is not None else None
        hit = answers.get(cache_key) if answers is not None and cache_key and not fresh else None
        if hit is not None:
            logger.info("answer cache hit")
            return _replay(hit, request)

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
        timings: dict[str, float] = {}
        top_k = body.top_k or settings.assistant_top_k
        started = time.monotonic()
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
            timings["plan"] = round(time.monotonic() - started, 2)
        judging = (
            not research
            and body.use_sources
            and body.rerank
            and getattr(assistant, "reranker", False)
        )
        # The judge picks from a few more excerpts than are shown.
        pool = min(top_k + 4, 20) if judging else top_k
        notices: list[str] = []

        def retrieve(q: str, limit: int) -> list:
            found, notice = hybrid_search(db, embedder, q, limit, settings.snippet_max_lines)
            if notice and notice not in notices:
                notices.append(notice)
            return found

        searched = time.monotonic()
        chunks = fuse([retrieve(q, pool) for q in queries], pool) if body.use_sources else []
        timings["search"] = round(time.monotonic() - searched, 2)
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
            judged = time.monotonic()
            verdicts = assistant.judge_chunks(query, candidates)
            chunks = rerank(candidates, verdicts, cutoff, top_k)
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
            timings["judge"] = round(time.monotonic() - judged, 2)
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
            web_search=body.web_search,
            max_tokens=body.max_tokens,
            format=body.format,
            include_drafts=body.include_drafts,
            strict=body.strict,
            search_queries=tuple(queries) if len(queries) > 1 else (),
            reranking=reranking,
            timings=timings,
            notice=notices[0] if notices else None,
            min_score=0.0 if notices and body.min_score is None else body.min_score,
            research=ResearchTools(
                search=lambda q: retrieve(q, 6),
                read=lambda path, start, end: read_span(db, path, start, end),
            )
            if research
            else None,
        )
        if streaming:
            events = _remembering(
                assistant.respond(question, chunks, body.history, mode, options), answers, cache_key
            )
            return StreamingResponse(
                _event_stream(events),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        try:
            response = assistant.answer(question, chunks, body.history, mode, options)
        except AssistantError as error:
            raise HTTPException(error.status_code, error.detail) from error
        _remember(response.model_dump(), answers, cache_key)
        return response

    answerer: Answerer = _resolve(request, get_answerer)
    chunks = search_symbols(db, embedder, question, body.top_k or 8, settings.snippet_max_lines)
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


def streaming_or_assistant(body: AskRequest, request: Request) -> bool:
    return "text/event-stream" in request.headers.get("accept", "") or body.for_assistant


def _cache_key(body: AskRequest, mode: str, db: Session) -> str | None:
    """The answer cache's key: the question, the conversation, every choice made and the
    knowledge base's version (its sources), so a new source answers afresh. None when
    this question is not to be cached."""
    if not body.cache or body.attachments:
        return None
    sources = db.execute(select(func.count(Source.id), func.max(Source.created_at))).one()
    choices = body.model_dump(exclude={"question", "history", "cache", "attachments"})
    history = [(t.role, t.content) for t in body.history[-6:]]
    return cache.key_of(
        " ".join(body.question.lower().split()), history, choices, mode, list(sources)
    )


def _remember(response: dict, answers: cache.TTLCache | None, key: str | None) -> None:
    if answers is not None and key and cache.answer_cacheable(response):
        answers.put(key, response)


def _remembering(
    events: Iterator[tuple[str, dict]], answers: cache.TTLCache | None, key: str | None
) -> Iterator[tuple[str, dict]]:
    """The assistant's events, keeping the finished answer for the cache."""
    for name, data in events:
        if name == "done":
            _remember(data, answers, key)
        yield name, data


def _replay(response: dict, request: Request):
    """A cached answer, sent the way a fresh one is."""
    data = {**response, "cached": True, "timings": {"answer": 0.0}}
    if "text/event-stream" not in request.headers.get("accept", ""):
        return AskResponse(**data)
    events = iter(
        [
            ("route", {"route": data.get("route"), "mode": "auto", "providers": []}),
            ("delta", {"text": data["answer"]}),
            ("done", data),
        ]
    )
    return StreamingResponse(
        _event_stream(events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
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
