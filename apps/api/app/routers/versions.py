"""Ingest versions: list a source's last three ingests, restore one, and preview what a
re-ingest would change."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session
from worker.versions import restore

from app.admin import ADMIN_REQUIRED, require_signed_admin
from app.config import settings
from app.db import get_db
from app.models import Source, SourceVersion
from app.ratelimit import rate_limit
from app.routers.sources import list_sources
from app.schemas import IngestPreview, Rollback, SourceItem, SourceVersionOut
from app.services.audit import record
from app.services.preview import PreviewError, preview
from app.services.webhooks import emit

router = APIRouter(
    tags=["ingest"],
    dependencies=[Depends(rate_limit("default", lambda: settings.rate_limit_per_minute))],
)


def _source(db: Session, source_id: int) -> Source:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(404, "No such source.")
    return source


@router.get(
    "/sources/{source_id}/versions",
    response_model=list[SourceVersionOut],
    summary="A source's kept versions",
    responses={404: {"description": "No such source."}},
)
def list_versions(
    source_id: int, db: Annotated[Session, Depends(get_db)]
) -> list[SourceVersionOut]:
    """The last three ingests of the source, newest first; any can be restored."""
    source = _source(db, source_id)
    rows = db.scalars(
        select(SourceVersion)
        .where(SourceVersion.source_key == source.key)
        .order_by(SourceVersion.version.desc())
    ).all()
    return [
        SourceVersionOut(
            version=v.version,
            created_at=v.created_at,
            files=v.files,
            symbols=v.symbols,
            current=v.version == source.version,
        )
        for v in rows
    ]


@router.post(
    "/sources/{source_id}/rollback",
    response_model=SourceItem,
    summary="Restore a kept version of a source",
    responses={**ADMIN_REQUIRED, 404: {"description": "No such source or version."}},
    dependencies=[Depends(require_signed_admin)],
)
def rollback(source_id: int, body: Rollback, db: Annotated[Session, Depends(get_db)]) -> SourceItem:
    """Makes a kept version current again, as a new version, so the rollback can itself
    be undone. Its files, passages, embeddings and graph come back as they were."""
    source = _source(db, source_id)
    key = source.key
    try:
        restored = restore(db, key, body.version)
    except LookupError as error:
        db.rollback()
        raise HTTPException(404, str(error)) from error
    db.commit()
    record(db, "admin", None, {"action": "rollback", "source": key, "to": body.version})
    emit("ingest", {"source": key, "status": "rolled back", "to_version": body.version}, db)
    return next(item for item in list_sources(db) if item.id == restored.id)


@router.post(
    "/sources/{source_id}/preview",
    response_model=IngestPreview,
    summary="What re-ingesting a source would change",
    responses={
        **ADMIN_REQUIRED,
        404: {"description": "No such source."},
        422: {"description": "The source cannot be fetched again (an upload, or an error)."},
    },
    dependencies=[Depends(require_signed_admin)],
)
async def ingest_preview(source_id: int, db: Annotated[Session, Depends(get_db)]) -> IngestPreview:
    """Fetches the source again and compares each file's hash with what is stored:
    added, changed and removed files, before anything is replaced."""
    source = await run_in_threadpool(_source, db, source_id)
    try:
        diff = await run_in_threadpool(preview, db, source)
    except PreviewError as error:
        raise HTTPException(422, str(error)) from error
    return IngestPreview(**diff)
