from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.ratelimit import rate_limit
from app.schemas import HealthReport, Liveness
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
    return code_health(db, max_function_loc=max_function_loc, min_fan_out=min_fan_out, limit=limit)


@router.get("/healthz", response_model=Liveness, tags=["ops"], summary="Liveness probe")
def healthz() -> Liveness:
    """Returns immediately without touching the database. Not rate limited."""
    return Liveness(status="ok")
