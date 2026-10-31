from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.admin import ADMIN_REQUIRED, require_admin
from app.config import settings
from app.db import get_db
from app.models import File, Source, Symbol
from app.ratelimit import rate_limit
from app.schemas import SiteConfig, SourceItem, SourceWeight
from app.services.weights import source_weight

router = APIRouter(
    tags=["ingest"],
    dependencies=[Depends(rate_limit("default", lambda: settings.rate_limit_per_minute))],
    responses={429: {"description": "Rate limit exceeded; see the Retry-After header."}},
)


@router.get("/sources", response_model=list[SourceItem], summary="List what has been ingested")
def list_sources(db: Annotated[Session, Depends(get_db)]) -> list[SourceItem]:
    """Returns every source in the knowledge base, newest first, with its size."""
    files = select(File.source_id, func.count().label("files")).group_by(File.source_id).subquery()
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
            weight=source_weight(source.kind, source.url, source.title, source.weight),
            weight_override=source.weight,
        )
        for source, file_count, symbol_count in rows
    ]


@router.get("/config", response_model=SiteConfig, summary="What this deployment allows")
def config() -> SiteConfig:
    """Tells the web app whether managing sources needs the admin password, and whether
    a model provider is configured for answering questions."""
    key = (
        settings.gemini_api_key if settings.llm_provider == "gemini" else settings.anthropic_api_key
    )
    # The chat page's assistant can use any of the services with a key.
    assistant_keys = (settings.groq_api_key, settings.openrouter_api_key, settings.mistral_api_key)
    return SiteConfig(
        admin_required=bool(settings.admin_token),
        chat_configured=bool(key) or any(assistant_keys),
    )


@router.post(
    "/admin/check",
    status_code=204,
    summary="Check the admin password",
    responses=ADMIN_REQUIRED,
    dependencies=[Depends(require_admin)],
)
def check_admin() -> Response:
    """Answers 204 if the request carries the admin password (or none is configured)."""
    return Response(status_code=204)


@router.patch(
    "/sources/{source_id}",
    response_model=SourceItem,
    summary="Set how much a source counts",
    responses={**ADMIN_REQUIRED, 404: {"description": "No such source."}},
    dependencies=[Depends(require_admin)],
)
def set_source_weight(
    source_id: int, body: SourceWeight, db: Annotated[Session, Depends(get_db)]
) -> SourceItem:
    """Sets a source's weight for answers: 3 primary (code, specs, official docs), 2
    secondary (Wikipedia, tutorials, blog posts), 1 derived (summaries, chat logs), or
    null to go back to the automatic weight. Admin only."""
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(404, "No such source.")
    source.weight = body.weight
    db.commit()
    return next(item for item in list_sources(db) if item.id == source_id)


@router.delete(
    "/sources/{source_id}",
    status_code=204,
    summary="Remove a source",
    responses={**ADMIN_REQUIRED, 404: {"description": "No such source."}},
    dependencies=[Depends(require_admin)],
)
def delete_source(source_id: int, db: Annotated[Session, Depends(get_db)]) -> Response:
    """Removes a source and everything ingested from it. Other sources are unaffected."""
    removed = db.execute(delete(Source).where(Source.id == source_id)).rowcount
    if not removed:
        raise HTTPException(404, "No such source.")
    db.commit()
    return Response(status_code=204)
