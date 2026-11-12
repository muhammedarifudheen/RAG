"""Analytics: the user's verdict on an answer, and the answer log queried."""

from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin import ADMIN_REQUIRED, require_admin
from app.config import settings
from app.db import get_db
from app.models import AnswerLog
from app.ratelimit import rate_limit, require_write_key
from app.services import analytics

router = APIRouter(
    tags=["analytics"],
    dependencies=[Depends(rate_limit("default", lambda: settings.rate_limit_per_minute))],
)

Metric = Literal[
    "top_questions",
    "failing",
    "gaps",
    "slowest",
    "sources",
    "drift",
    "feedback",
    "budget",
    "shadow",
]


class Feedback(BaseModel):
    """Names the answer by `answer_hash` (best), else the query by `query_hash`, else the
    `question` text (the original contract, still accepted)."""

    question: str | None = Field(default=None, min_length=1, max_length=2000)
    query_hash: str | None = Field(default=None, max_length=64)
    answer_hash: str | None = Field(default=None, max_length=64)
    rating: Literal["up", "down"]
    reason: str | None = Field(default=None, max_length=500)
    chat: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def names_something(self) -> Self:
        if not (self.question or self.query_hash or self.answer_hash):
            raise ValueError("give an answer_hash, a query_hash or the question")
        return self


@router.post(
    "/feedback",
    status_code=204,
    summary="Rate an answer",
    responses={404: {"description": "No logged answer matches."}},
    dependencies=[Depends(require_write_key)],
)
def feedback(body: Feedback, db: Annotated[Session, Depends(get_db)]) -> Response:
    """👍 or 👎 (with a reason) on one answer: by `answer_hash`, else the latest answer with
    `query_hash`, else the latest to `question` (in `chat`, if given). The rating is stored
    with the chunk orders served and scored in shadow, so ratings can be compared by order.
    Thumbs down feed the failing-questions list."""
    query = select(AnswerLog)
    if body.answer_hash:
        query = query.where(AnswerLog.answer_hash == body.answer_hash)
    elif body.query_hash:
        query = query.where(AnswerLog.query_hash == body.query_hash)
    else:
        query = query.where(AnswerLog.question == (body.question or "").strip()[:2000])
    if body.chat:
        query = query.where(AnswerLog.chat_id == body.chat)
    row = db.scalars(query.order_by(AnswerLog.id.desc())).first()
    if row is None:
        raise HTTPException(404, "No logged answer matches.")
    row.feedback = 1 if body.rating == "up" else -1
    row.feedback_reason = (body.reason or "").strip() or None
    row.feedback_at = datetime.now(UTC)
    db.commit()
    return Response(status_code=204)


@router.get(
    "/analytics",
    summary="Query the answer log",
    responses=ADMIN_REQUIRED,
    dependencies=[Depends(require_admin)],
)
def query(
    db: Annotated[Session, Depends(get_db)],
    metric: Annotated[Metric, Query()],
    window: Annotated[int, Query(ge=1, le=365, description="Days back.")] = 7,
    filter: Annotated[
        str | None,
        Query(max_length=200, description='"mode:ASK", "state:absent", or words in the question.'),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> dict:
    """top_questions, failing (thumbs down or unchecked citations), gaps (absent or
    partial), slowest, sources (retrieved and cited), drift (week over week: hit rate,
    latency, faithfulness, approval) or feedback. This is analytics.query."""
    return analytics.query(db, metric, window, filter, limit)


@router.get(
    "/export/analytics.csv",
    summary="An analytics query as CSV",
    response_class=PlainTextResponse,
    responses={**ADMIN_REQUIRED, 200: {"content": {"text/csv": {}}}},
    dependencies=[Depends(require_admin)],
)
def export_csv(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    metric: Annotated[Metric, Query()],
    window: Annotated[int, Query(ge=1, le=365)] = 30,
) -> PlainTextResponse:
    result = analytics.query(db, metric, window, None, 100)
    return PlainTextResponse(
        analytics.as_csv(result),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="atlas-{metric}.csv"'},
    )
