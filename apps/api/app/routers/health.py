from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin import ADMIN_REQUIRED, require_admin
from app.assistant import Assistant, get_assistant
from app.config import settings
from app.db import get_db
from app.models import KnowledgeAudit, Source
from app.ratelimit import rate_limit
from app.schemas import HealthReport, KnowledgeAuditOut, Liveness
from app.services.catalog import source_catalog
from app.services.health import code_health

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthReport,
    tags=["health"],
    summary="Code health report",
    responses={429: {"description": "Rate limit exceeded; see the Retry-After header."}},
    dependencies=[Depends(rate_limit("default", lambda: settings.rate_limit_per_minute))],
)
def health(
    db: Annotated[Session, Depends(get_db)],
    max_function_loc: Annotated[
        int, Query(ge=1, description="Functions longer than this many lines are reported.")
    ] = 50,
    min_fan_out: Annotated[
        int, Query(ge=1, description="Files depending on at least this many files are reported.")
    ] = 10,
    limit: Annotated[int, Query(ge=1, le=1000, description="Maximum entries per list.")] = 100,
) -> HealthReport:
    """Computes four measures over the ingested repository:

    - **Dead symbols**: functions and methods that nothing calls or imports. Entry points
      (`main`, `init`, constructors, dunder methods, tests) are left out. The call graph
      only holds calls the worker could resolve, so treat these as candidates: a method
      reached only through a variable, or declared on an interface, will appear here.
    - **Circular dependencies**: groups of files that depend on each other, and groups
      of symbols that call each other, directly or through intermediaries.
    - **Long functions**: functions and methods longer than `max_function_loc` lines.
    - **High fan-out files**: files depending on at least `min_fan_out` other files.

    `summary` gives totals; each list is capped at `limit`. This is a report on the
    code, not a liveness probe: use `/healthz` for that."""
    report = code_health(
        db, max_function_loc=max_function_loc, min_fan_out=min_fan_out, limit=limit
    )
    return report.model_copy(update={"knowledge_audit": _latest_audit(db)})


@router.post(
    "/health",
    response_model=KnowledgeAuditOut,
    tags=["health"],
    summary="Audit the knowledge base",
    responses={
        **ADMIN_REQUIRED,
        409: {"description": "Nothing has been ingested yet."},
        429: {"description": "Rate limit exceeded; see the Retry-After header."},
        503: {"description": "No model wrote the audit in time."},
    },
    dependencies=[
        Depends(require_admin),
        Depends(rate_limit("ask", lambda: settings.ask_rate_limit_per_minute)),
    ],
)
def audit(
    db: Annotated[Session, Depends(get_db)],
    assistant: Annotated[Assistant, Depends(get_assistant)],
) -> KnowledgeAuditOut:
    """Has a model audit every source (coverage, staleness, overlap with other sources,
    three questions it cannot answer) as a Markdown table, and keeps it: `GET /health`
    returns the newest. Run weekly, and after each deploy, by the knowledge-audit
    workflow. Admin only."""
    catalog = source_catalog(db)
    if not catalog:
        raise HTTPException(409, "The knowledge base is empty; add a source first.")
    written = assistant.audit_sources(catalog)
    if written is None:
        raise HTTPException(503, "No model wrote the audit in time; try again in a minute.")
    report, model = written
    sources = db.scalar(select(func.count()).select_from(Source)) or 0
    row = KnowledgeAudit(report=report, model=model, sources=sources)
    db.add(row)
    db.commit()
    db.refresh(row)
    return KnowledgeAuditOut(
        report=row.report, model=row.model, sources=row.sources, created_at=row.created_at
    )


def _latest_audit(db: Session) -> KnowledgeAuditOut | None:
    row = db.scalars(
        select(KnowledgeAudit).order_by(KnowledgeAudit.created_at.desc(), KnowledgeAudit.id.desc())
    ).first()
    if row is None:
        return None
    return KnowledgeAuditOut(
        report=row.report, model=row.model, sources=row.sources, created_at=row.created_at
    )


@router.get("/healthz", response_model=Liveness, tags=["ops"], summary="Liveness probe")
def healthz() -> Liveness:
    """Returns immediately without touching the database. Not rate limited."""
    return Liveness(status="ok")
