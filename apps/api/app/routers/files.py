from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.ratelimit import rate_limit
from app.schemas import FileDetail, FileGraph
from app.services.files import file_detail, file_graph

router = APIRouter(
    dependencies=[Depends(rate_limit("default", lambda: settings.rate_limit_per_minute))],
    responses={429: {"description": "Rate limit exceeded; see the Retry-After header."}},
)


@router.get(
    "/graph/files",
    response_model=FileGraph,
    tags=["graph"],
    summary="Dependency graph between files",
)
def graph_files(db: Annotated[Session, Depends(get_db)]) -> FileGraph:
    """Returns every ingested file as a node and one edge per pair of files, with the
    number of import, call and inheritance edges between their symbols.

    Files and edges that are part of a circular dependency are marked `in_cycle`."""
    return file_graph(db)


@router.get(
    "/file",
    response_model=FileDetail,
    tags=["files"],
    summary="Source and symbols of one file",
    responses={404: {"description": "No ingested file has this path."}},
)
def file(
    path: Annotated[
        str,
        Query(min_length=1, description="File path as stored, relative to the repository root."),
    ],
    db: Annotated[Session, Depends(get_db)],
) -> FileDetail:
    """Returns the file's full source text and the symbols defined in it, in line order."""
    result = file_detail(db, path)
    if result is None:
        raise HTTPException(404, f"No ingested file at {path!r}.")
    return result
