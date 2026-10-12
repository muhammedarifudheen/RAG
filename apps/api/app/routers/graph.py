from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.ratelimit import rate_limit
from app.schemas import GraphResponse
from app.services.graph import call_graph

router = APIRouter(
    tags=["graph"],
    dependencies=[Depends(rate_limit("default", lambda: settings.rate_limit_per_minute))],
)


@router.get(
    "/graph",
    response_model=GraphResponse,
    summary="Call graph around a file",
    responses={
        404: {"description": "No ingested file has this path."},
        429: {"description": "Rate limit exceeded; see the Retry-After header."},
    },
)
def graph(
    file: Annotated[
        str,
        Query(min_length=1, description="File path as stored, relative to the repository root."),
    ],
    db: Annotated[Session, Depends(get_db)],
    hops: Annotated[int, Query(ge=1, le=5, description="How many calls to follow.")] = 1,
    direction: Annotated[
        Literal["both", "callers", "callees"],
        Query(description="Follow calls made by the file, calls into it, or both."),
    ] = "both",
) -> GraphResponse:
    """Returns the symbols within `hops` calls of the file's own symbols, and the `calls`
    edges between them. Nodes carry their distance from the file in `depth`.

    Only calls the ingestion worker could resolve are present, so the graph can be
    missing edges but does not contain guessed ones."""
    result = call_graph(db, file, hops, direction)
    if result is None:
        raise HTTPException(404, f"No ingested file at {file!r}.")
    return result
