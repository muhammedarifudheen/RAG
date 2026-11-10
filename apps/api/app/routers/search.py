import json
import logging
import queue
import threading
import time
from collections.abc import Callable, Iterator
from typing import Annotated, Literal, TypeVar

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.assistant import Assistant, AssistantError, Options, cache, get_assistant
from app.assistant.agent import ResearchTools
from app.assistant.gaps import suggested_source
from app.assistant.mcp_client import call_tool, external_tools
from app.assistant.modes import classify_mode
from app.assistant.planner import fuse
from app.assistant.rerank import rerank
from app.assistant.router import wants_research
from app.assistant.service import with_footer
from app.config import settings
from app.db import SessionLocal, get_db
from app.embedding import Embedder, get_embedder
from app.llm import Answerer, AnswerError, get_answerer
from app.models import Source
from app.ratelimit import rate_limit
from app.retrieval import reranker, scoring, state
from app.retrieval.budget import Budget, Trace, run_stage, stage_timer
from app.retrieval.topk import adaptive_top_k
from app.schemas import (
    AskRequest,
    AskResponse,
    GapReport,
    KnowledgeHealth,
    Reranking,
    SearchResponse,
)
from app.security import REFUSED, allowed_hosts, digest, injection
from app.services import kg
from app.services.agent_tools import analytics_text, fetch_page, health_text
from app.services.audit import answer_event, record, text_hash
from app.services.catalog import mentions_sources, source_catalog
from app.services.explore import audit_answer, explore
from app.services.knowledge import health_note, knowledge_health, log_answer, note_suggestion
from app.services.search import extract_citations, hybrid_search, search_symbols
from app.services.spans import read_span
from app.services.webhooks import emit, query_event

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


def _shadow_score(query: str, chunks: list, candidates: list) -> None:
    """Scores the weighted order for the log only, after the response has gone out. It opens its
    own session (the request's is closed by then) and never raises: a failure is logged as
    `shadow_score_errors`, apart from the retrieval line, and the caller never sees it."""
    started = time.monotonic()
    try:
        with SessionLocal() as db:
            rates = state.source_hit_rates(db)
        ranked = scoring.rank(chunks, query, candidates=candidates, hit_rates=rates)
        logger.info(
            "shadow_score %s",
            json.dumps(
                {
                    "query_hash": text_hash(query)[:12],
                    "shadow_score_ms": round((time.monotonic() - started) * 1000, 2),
                    "shadow_chosen": [c.symbol_id for c, _ in ranked],
                    "shadow_final_scores": [round(s, 4) for _, s in ranked],
                }
            ),
        )
    except Exception:
        logger.exception(
            "shadow_score_errors %s",
            json.dumps({"shadow_score_ms": round((time.monotonic() - started) * 1000, 2)}),
        )


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
    background: BackgroundTasks,
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
    chat: Annotated[
        str | None,
        Header(
            alias="X-Atlas-Chat",
            max_length=64,
            description="Assistant only: the chat this question belongs to, for the answer log "
            "and the chat's knowledge-health note.",
        ),
    ] = None,
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
    # Clear prompt-injection attempts are refused, neutrally, and recorded.
    last_user = next((t.content for t in reversed(body.history) if t.role == "user"), "")
    attack = injection(question) or injection(last_user)
    if attack:
        record(db, "injection", None, {"pattern": attack, "query": text_hash(question)})
        raise HTTPException(400, REFUSED)
    # Grounded unless the request opens it to the web and general knowledge.
    grounded = settings.assistant_grounded and request.headers.get("x-atlas-open") != "true"
    arrived = time.monotonic()

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
            # Asked again: it counts for the knowledge health all the same.
            log_answer(db, embedder, {**hit, "question": question}, chat)
            return _replay(hit, request)

    if body.task == "health":
        health = knowledge_health(db, chat)
        return AskResponse(
            question=question,
            answer=health_note(health),
            citations=[],
            chunks=[],
            model="atlas",
            complete=True,
            knowledge_health=KnowledgeHealth(**health),
        )

    if body.task == "challenge":
        # The self-challenge of an answer already given, against the excerpts it was given.
        if not (body.answer or "").strip():
            raise HTTPException(422, "answer must be given to challenge it.")
        challenger: Assistant = _resolve(request, get_assistant)
        found = challenger.challenge(question, body.answer, body.chunks, body.attachments)
        if found is None:
            raise HTTPException(503, "The self-challenge is busy; try again in a minute.")
        final, report = found
        return AskResponse(
            question=question,
            answer=final,
            citations=extract_citations(final, body.chunks),
            chunks=body.chunks,
            model=report.challenged_by,
            complete=True,
            challenge=report,
        )

    if body.task == "gaps":
        # What the knowledge base would need to answer the question.
        finder: Assistant = _resolve(request, get_assistant)
        found = finder.find_gaps(question, source_catalog(db))
        if found is None:
            raise HTTPException(503, "The gap finder is busy; try again in a minute.")
        report, found_by = found
        note_suggestion(db, question, chat, suggested_source(report))
        emit(
            "gap",
            {
                "question": question,
                "found_by": "gap finder",
                "report": report,
                "suggestion_url": suggested_source(report),
            },
            db,
        )
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
        # The mode first: by intent, unless the request chose one.
        atlas_mode = body.atlas_mode or (
            classify_mode(question) if body.task == "answer" else "ASK"
        )
        if atlas_mode in ("AUDIT", "EXPLORE") and body.task == "answer":
            return _prepared(
                _mode_answer(atlas_mode, question, db, embedder), request, arrived, grounded
            )
        timings: dict[str, float] = {}
        trace = Trace(timings=timings)
        budget = Budget()  # each stage's time against the latency budget
        # An explicit top_k stands; otherwise 3, 5 or 8 by the kind of question (never more
        # than 8), or the server's default.
        if body.top_k:
            top_k = body.top_k
        elif settings.retrieval_adaptive_top_k:
            top_k = adaptive_top_k(question)
        else:
            top_k = settings.assistant_top_k
        queries = [query]
        research = body.use_sources and (
            body.research
            if body.research is not None
            else atlas_mode == "AGENT"
            or (settings.assistant_research_auto and wants_research(question))
        )
        # Researching, the agent plans its own searches and reads what it needs: no
        # planner or judge.
        planning = body.use_sources and body.plan_queries and getattr(assistant, "planner", False)
        if planning and not research:
            plan_budget = settings.retrieval_plan_budget
            if "rewrite" in budget.enforce:  # enforced: the planner gets only its budget
                plan_budget = min(plan_budget, budget.limits["rewrite"] / 1000)
            queries = run_stage(
                trace,
                "plan",
                lambda: assistant.plan_queries(query),
                [query],
                plan_budget,
                reason="query planner too slow; searched the question as asked",
            )
            budget.record("rewrite", timings["plan"] * 1000)
        # ATLAS_RERANK=on: a cross-encoder replaces the model-by-model relevance judge.
        cross = not research and body.use_sources and body.rerank and reranker.enabled()
        judging = (
            not research
            and not cross
            and body.use_sources
            and body.rerank
            and getattr(assistant, "reranker", False)
        )
        # The judge picks from a few more excerpts than are shown; the cross-encoder reads 20.
        if cross:
            pool = reranker.CANDIDATES
        else:
            pool = min(top_k + 4, 20) if judging else top_k
        notices: list[str] = []

        version = state.kb_version(db) if settings.retrieval_cache else ""

        def retrieve(q: str, limit: int) -> list:
            # Copies in and out: later stages set scores on the excerpts, which must not
            # leak into the cache.
            key = state.retrieval_key(q, limit, body.as_of, version)
            cached = state.RETRIEVALS.get(key) if settings.retrieval_cache else None
            if cached is not None:
                if "retrieval" not in trace.cache_hits:
                    trace.cache_hits.append("retrieval")
                return [c.model_copy() for c in cached[0]]
            found, notice = hybrid_search(
                db, embedder, q, limit, settings.snippet_max_lines, as_of=body.as_of, budget=budget
            )
            if notice and notice not in notices:
                notices.append(notice)
            if settings.retrieval_cache and not notice:  # a fallback's results are not kept
                state.RETRIEVALS.put(key, ([c.model_copy() for c in found], None))
            return found

        searched = time.monotonic()
        found_lists: list[list] = []
        for q in queries if body.use_sources else []:
            found_lists.append(retrieve(q, pool))
            if budget.skip_optional():
                break  # a stage is over its enforced budget: the other planned searches are optional
        with stage_timer(budget, "fuse"):
            chunks = fuse(found_lists, pool) if body.use_sources else []
        timings["search"] = round(time.monotonic() - searched, 2)
        for notice in notices:
            trace.degrade(notice.rstrip("."))
        fused_order = list(chunks)  # the retrieval order, the rank-fusion signal
        reranking = None
        if (cross or judging) and chunks and budget.skip_optional():
            # Over an enforced budget already: the reranker (or the judge) is the optional stage.
            trace.degrade(f"{budget.enforced_breaches[0]} over its budget; skipped reranking")
            trace.reason_code = trace.reason_code or f"budget_{budget.enforced_breaches[0]}"
            chunks = chunks[: (body.top_k or reranker.KEEP) if cross else top_k]
            cross = judging = False
        if cross and chunks:
            cross_timeout = None
            if "rerank" in budget.enforce:
                cross_timeout = (
                    min(settings.atlas_rerank_timeout_ms, budget.limits["rerank"]) / 1000
                )
            chunks = reranker.rerank(
                trace, query, chunks, body.top_k or reranker.KEEP, timeout=cross_timeout
            )
            budget.record("rerank", (trace.extra.get("rerank") or {}).get("rerank_ms", 0.0))
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
            judge_budget = settings.retrieval_judge_budget
            if "rerank" in budget.enforce:
                judge_budget = min(judge_budget, budget.limits["rerank"] / 1000)
            verdicts = run_stage(
                trace,
                "judge_calls",
                lambda: assistant.judge_chunks(query, candidates),
                {},
                judge_budget,
                reason="relevance judge too slow; kept the search order",
            )
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
            timings.pop("judge_calls", None)
            budget.record("rerank", (time.monotonic() - judged) * 1000)
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
        weighted = (
            settings.retrieval_weighted_rank if body.weighted_rank is None else body.weighted_rank
        )
        if weighted and chunks:
            ranked_at = time.monotonic()
            try:
                rates = state.source_hit_rates(db)
            except Exception:
                logger.exception("source hit rates unavailable; ranking without them")
                db.rollback()
                rates = {}
            scored = scoring.rank(chunks, query, candidates=fused_order, hit_rates=rates)
            chunks = [c.model_copy(update={"final_score": round(s, 4)}) for c, s in scored]
            timings["rank"] = round(time.monotonic() - ranked_at, 3)
        # Shadow mode: with the weighted order off it is still scored, after the response is
        # sent (see `_shadow_score`), so it never adds to the latency a caller sees.
        shadow_job = (
            (lambda: _shadow_score(query, chunks, fused_order)) if not weighted and chunks else None
        )
        # One line per query: what each stage retrieved and chose, how long it took, what
        # the caches and the budgets did.
        rr = trace.extra.get("rerank") or {}
        logger.info(
            "retrieval %s",
            json.dumps(
                {
                    "query_hash": text_hash(query)[:12],
                    "queries": queries,
                    "kb_version": version,
                    "top_k": top_k,
                    "retrieved": [c.symbol_id for c in fused_order],
                    "chosen": [c.symbol_id for c in chunks],
                    "final_scores": [c.final_score for c in chunks],
                    "rerank_scores": [c.rerank_score for c in chunks],
                    "rerank_ms": rr.get("rerank_ms"),
                    "rerank_batches": rr.get("rerank_batches"),
                    "rerank_timed_out": rr.get("rerank_timed_out"),
                    "degraded_reason": trace.reason_code,
                    "relevance": [c.relevance for c in chunks],
                    "weighted": bool(weighted),
                    "timings": timings,
                    "stage_ms": budget.snapshot(),
                    "budget_breached": budget.first_breach,
                    "cache_hits": trace.cache_hits,
                    "degraded": trace.degraded,
                }
            ),
        )
        options = Options(
            degraded=tuple(trace.degraded),
            degraded_reason=trace.reason_code,
            budget=budget,
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
            about_sources=bool(body.use_sources and mentions_sources(db, question)),
            grounded=grounded,
            mode="AGENT" if research else atlas_mode,
            started=arrived,
            allowed_hosts=frozenset(allowed_hosts(db.scalars(select(Source.url))))
            if grounded
            else None,
            timings=timings,
            notice=notices[0] if notices else None,
            min_score=0.0 if notices and body.min_score is None else body.min_score,
            research=ResearchTools(
                search=lambda q: retrieve(q, 6),
                read=lambda path, start, end: read_span(db, path, start, end),
                # External MCP servers' read-only tools, when ATLAS_MCP_SERVERS names some.
                external=[t.described() for t in external_tools()],
                call=call_tool if settings.atlas_mcp_servers else None,
                graph=lambda node, depth, edge: kg.walk(db, node, depth, edge),
                analytics=lambda metric, window, found: analytics_text(db, metric, window, found),
                health=lambda: health_text(db),
                fetch=lambda url: fetch_page(db, url),
            )
            if research
            else None,
        )
        if streaming:
            events = _remembering(
                assistant.respond(question, chunks, body.history, mode, options),
                answers,
                cache_key,
                lambda data: _after(db, embedder, question, data, chat),
            )
            return StreamingResponse(
                _event_stream(events),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                background=BackgroundTask(shadow_job) if shadow_job else None,
            )
        if shadow_job:
            background.add_task(shadow_job)
        try:
            response = assistant.answer(question, chunks, body.history, mode, options)
        except AssistantError as error:
            raise HTTPException(error.status_code, error.detail) from error
        _remember(response.model_dump(), answers, cache_key)
        _after(db, embedder, question, response.model_dump(), chat)
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


def _after(db: Session, embedder: Embedder, question: str, data: dict, chat: str | None) -> None:
    """An answer's records: the knowledge log, and the audit trail (hashes and ids)."""
    log_answer(db, embedder, data, chat)
    record(db, "answer", digest(chat), answer_event(question, data))
    emit("query", query_event(question, data), db)
    kg.note_answer(db, data)
    if data.get("epistemic") in ("absent", "partial"):
        emit("gap", {"question": question, "found_by": "answer", "state": data["epistemic"]}, db)
    if data.get("redacted"):
        record(db, "redaction", digest(chat), {"kinds": data["redacted"]})


def _mode_answer(mode: str, question: str, db: Session, embedder: Embedder) -> dict:
    """An EXPLORE or AUDIT answer, from the database."""
    asked = kg.parse_question(question) if mode == "EXPLORE" else None
    if mode == "AUDIT":
        answer, chunks = audit_answer(db), []
    elif asked is not None and asked[0] != "callers":
        # A question about the knowledge graph: paths, dependencies, contradictions,
        # what supersedes what; answered from the graph, each node cited.
        answer, graph = kg.answer(db, question) or ("", {})
        refs = [n["id"] for n in graph.get("nodes", []) if n.get("citation")][:8]
        chunks = [c for c in (kg.as_excerpt(db, ref) for ref in refs) if c is not None]
    else:
        chunks, _ = hybrid_search(db, embedder, question, 3, settings.snippet_max_lines)
        answer = explore(db, chunks)
    return {
        "question": question,
        "answer": answer,
        "citations": [c.model_dump() for c in extract_citations(answer, chunks)],
        "chunks": [c.model_dump() for c in chunks],
        "model": "atlas",
        "complete": True,
        "provider": "Atlas",
        "route": "sources",
        "suggestions": [],
        "mode": mode,
        # Read from the database itself: known, or absent if nothing matched.
        "epistemic": "known" if mode == "AUDIT" or chunks else "absent",
    }


def _prepared(data: dict, request: Request, arrived: float, grounded: bool):
    """An answer made without a model, sent the way a model's is."""
    data = with_footer(
        {**data, "grounded": grounded},
        Options(mode=data["mode"], started=arrived),
    )
    if "text/event-stream" not in request.headers.get("accept", ""):
        return AskResponse(**data)
    events = iter(
        [
            ("mode", {"mode": data["mode"]}),
            ("route", {"route": data["route"], "mode": "auto", "providers": []}),
            ("delta", {"text": data["answer"]}),
            ("done", data),
        ]
    )
    return StreamingResponse(
        _event_stream(events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def streaming_or_assistant(body: AskRequest, request: Request) -> bool:
    return "text/event-stream" in request.headers.get("accept", "") or body.for_assistant


def _cache_key(body: AskRequest, mode: str, db: Session) -> str | None:
    """The answer cache's key: the question, the conversation, every choice made and the
    knowledge base's version (its sources), so a new source answers afresh. None when
    this question is not to be cached."""
    if not body.cache or body.attachments:
        return None
    version = state.kb_version(db)
    choices = body.model_dump(exclude={"question", "history", "cache", "attachments"})
    history = [(t.role, t.content) for t in body.history[-6:]]
    return cache.key_of(" ".join(body.question.lower().split()), history, choices, mode, version)


def _remember(response: dict, answers: cache.TTLCache | None, key: str | None) -> None:
    if answers is not None and key and cache.answer_cacheable(response):
        # A miss ("absent") is kept an hour, not a day: the source that answers it may be
        # about to be added, and an ingest changes the key anyway.
        absent = response.get("epistemic") == "absent"
        answers.put(key, response, ttl=cache.HOUR if absent else None)


def _remembering(
    events: Iterator[tuple[str, dict]],
    answers: cache.TTLCache | None,
    key: str | None,
    log: Callable[[dict], object],
) -> Iterator[tuple[str, dict]]:
    """The assistant's events, keeping the finished answer for the cache and the log."""
    for name, data in events:
        if name == "done":
            _remember(data, answers, key)
            log(data)
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
        yield f"event: {name}\ndata: {json.dumps(data, default=_plain)}\n\n"


def _plain(value: object) -> str:
    """Dates (an excerpt's ingest, an answer's freshness) as ISO 8601, for JSON."""
    return value.isoformat() if hasattr(value, "isoformat") else str(value)
