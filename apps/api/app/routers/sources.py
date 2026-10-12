from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import File, Source, Symbol
from app.ratelimit import rate_limit
from app.schemas import SourceItem

router = APIRouter(
    tags=["ingest"],
    dependencies=[Depends(rate_limit("default", lambda: settings.rate_limit_per_minute))],
    responses={429: {"description": "Rate limit exceeded; see the Retry-After header."}},
)


@router.get("/sources", response_model=list[SourceItem], summary="List what has been ingested")
def list_sources(db: Annotated[Session, Depends(get_db)]) -> list[SourceItem]:
    """Returns every source in the knowledge base, newest first, with its size."""
    files = (
        select(File.source_id, func.count().label("files"))
        .group_by(File.source_id)
        .subquery()
    )
    symbols = (
        select(File.source_id, func.count().label("symbols"))
        .join(Symbol, Symbol.file_id == File.id)
        .group_by(File.source_id)
        .subquery()
    )
    rows = db.execute(
        select(Source, func.coalesce(files.c.files, 0), func.coalesce(symbols.c.symbols, 0))
        .outerjoin(files, files.c.source_id == Source.id)
        .outerjoin(symbols, symbols.c.source_id == Source.id)
        .order_by(Source.created_at.desc(), Source.id.desc())
    ).all()
    return [
        SourceItem(
            id=source.id,
            kind=source.kind,
            title=source.title,
            url=source.url,
            created_at=source.created_at,
            files=file_count,
            symbols=symbol_count,
        )
        for source, file_count, symbol_count in rows
    ]


@router.delete(
    "/sources/{source_id}",
    status_code=204,
    summary="Remove a source",
    responses={404: {"description": "No such source."}},
)
def delete_source(source_id: int, db: Annotated[Session, Depends(get_db)]) -> Response:
    """Removes a source and everything ingested from it. Other sources are unaffected."""
    removed = db.execute(delete(Source).where(Source.id == source_id)).rowcount
    if not removed:
        raise HTTPException(404, "No such source.")
    db.commit()
    return Response(status_code=204)
