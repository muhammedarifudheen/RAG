from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.embedding import Embedder, get_embedder
from app.llm import Answerer, AnswerError, get_answerer
from app.ratelimit import rate_limit
from app.schemas import AskRequest, AskResponse, SearchResponse
from app.services.search import extract_citations, search_symbols

RATE_LIMITED = {429: {"description": "Rate limit exceeded; see the Retry-After header."}}

router = APIRouter(tags=["search"])


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
        409: {"description": "Nothing has been ingested yet."},
        422: {"description": "Invalid request, or the model declined to answer."},
        502: {"description": "The model provider (Anthropic or Gemini) failed."},
        503: {"description": "The model provider is not configured, rejected the key, or is rate limiting."},
    },
    dependencies=[Depends(rate_limit("ask", lambda: settings.ask_rate_limit_per_minute))],
)
def ask(
    body: AskRequest,
    db: Annotated[Session, Depends(get_db)],
    embedder: Annotated[Embedder, Depends(get_embedder)],
    answerer: Annotated[Answerer, Depends(get_answerer)],
) -> AskResponse:
    """Runs the same vector search as `/search`, sends the top results and the question
    to the configured model (Claude or Gemini), and returns the answer with inline
    `[path:start-end]` citations.

    `chunks` holds the excerpts that were sent to the model. Each entry in `citations` is
    `verified` only if its lines lie inside one of those chunks."""
    question = body.question.strip()
    if not question:
        raise HTTPException(422, "question must not be blank.")

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
