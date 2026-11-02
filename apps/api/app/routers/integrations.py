"""Integrations: webhooks, GitHub's push hook (re-indexing), and exports."""

import hashlib
import hmac
import json
import secrets
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from worker.clone import parse_github_url

from app.admin import ADMIN_REQUIRED, require_admin, require_signed_admin
from app.config import settings
from app.db import get_db
from app.models import Source, Webhook
from app.ratelimit import rate_limit
from app.routers.ingest import reindex
from app.schemas import WebhookCreate, WebhookCreated, WebhookOut
from app.services import webhooks
from app.services.audit import record
from app.services.export import audit_markdown, qa_lines

router = APIRouter(
    tags=["integrations"],
    dependencies=[Depends(rate_limit("default", lambda: settings.rate_limit_per_minute))],
)


def _out(row: Webhook) -> WebhookOut:
    return WebhookOut(
        id=row.id,
        url=row.url,
        events=row.events or list(webhooks.EVENTS),
        created_at=row.created_at,
        last_status=row.last_status,
        last_at=row.last_at,
    )


@router.get(
    "/webhooks",
    response_model=list[WebhookOut],
    summary="List the webhooks",
    responses=ADMIN_REQUIRED,
    dependencies=[Depends(require_admin)],
)
def list_webhooks(db: Annotated[Session, Depends(get_db)]) -> list[WebhookOut]:
    """The addresses told about ingests, answers and gaps: the admin's, newest first, then
    those set on the server (ATLAS_WEBHOOKS)."""
    rows = [_out(w) for w in db.scalars(select(Webhook).order_by(Webhook.id.desc()))]
    return rows + [
        WebhookOut(id=None, url=url, events=list(webhooks.EVENTS), configured=True)
        for url in webhooks.configured()
    ]


@router.post(
    "/webhooks",
    response_model=WebhookCreated,
    status_code=201,
    summary="Add a webhook",
    responses={**ADMIN_REQUIRED, 422: {"description": "Not a public http(s) address."}},
    dependencies=[Depends(require_signed_admin)],
)
def create_webhook(body: WebhookCreate, db: Annotated[Session, Depends(get_db)]) -> WebhookCreated:
    """Posts each chosen event to `url` as JSON, `{"event", "id", "at", "data"}`, with
    `X-Atlas-Event`, `X-Atlas-Delivery` and `X-Atlas-Signature-256: sha256=<HMAC-SHA256 of
    the body with the secret>`. The secret is shown only now. Deliveries are tried twice
    and never slow the request that caused them."""
    try:
        url = webhooks.check_url(body.url.strip())
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    secret = "whsec_" + secrets.token_urlsafe(32)
    row = Webhook(url=url, secret=secret, events=sorted(set(body.events)))
    db.add(row)
    db.commit()
    db.refresh(row)
    record(db, "admin", None, {"action": "add webhook", "id": row.id, "events": row.events})
    return WebhookCreated(**_out(row).model_dump(), secret=secret)


@router.delete(
    "/webhooks/{webhook_id}",
    status_code=204,
    summary="Remove a webhook",
    responses={**ADMIN_REQUIRED, 404: {"description": "No such webhook."}},
    dependencies=[Depends(require_signed_admin)],
)
def delete_webhook(webhook_id: int, db: Annotated[Session, Depends(get_db)]) -> Response:
    row = db.get(Webhook, webhook_id)
    if row is None:
        raise HTTPException(404, "No such webhook.")
    db.delete(row)
    db.commit()
    record(db, "admin", None, {"action": "remove webhook", "id": webhook_id})
    return Response(status_code=204)


@router.post(
    "/hooks/github",
    status_code=202,
    summary="GitHub push: re-index the repository",
    responses={
        401: {"description": "The X-Hub-Signature-256 does not match."},
        404: {"description": "Re-indexing on push is not configured (GITHUB_WEBHOOK_SECRET)."},
    },
)
async def github_push(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    event: Annotated[str, Header(alias="X-GitHub-Event")] = "",
    signature: Annotated[str, Header(alias="X-Hub-Signature-256")] = "",
) -> dict:
    """Point a repository's webhook here (content type `application/json`, the push event,
    with the server's GITHUB_WEBHOOK_SECRET). A push to the default branch of a repository
    that is a source re-indexes it in the background; other deliveries are acknowledged
    and ignored."""
    secret = settings.github_webhook_secret
    if not secret:
        raise HTTPException(404, "Re-indexing on push is not configured.")
    body = await request.body()
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        record(db, "auth", None, {"action": "github hook", "result": "bad signature"})
        raise HTTPException(401, "The signature does not match.")
    if event == "ping":
        return {"status": "pong"}
    if event != "push":
        return {"status": "ignored", "reason": f"{event or 'unknown'} events are not used"}
    try:
        payload = json.loads(body)
        repository = payload["repository"]
        owner, name = parse_github_url(repository["html_url"])
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(422, "Not a push from a GitHub repository.") from error
    if payload.get("ref") != f"refs/heads/{repository.get('default_branch')}":
        return {"status": "ignored", "reason": "not the default branch"}
    key = f"repo:{owner}/{name}".lower()
    found = await run_in_threadpool(
        lambda: db.scalars(select(Source.id).where(Source.key == key)).first()
    )
    if found is None:
        return {"status": "ignored", "reason": f"{owner}/{name} is not a source"}
    queued = reindex(f"https://github.com/{owner}/{name}")
    record(db, "admin", None, {"action": "reindex on push", "repository": f"{owner}/{name}"})
    return {"status": "reindexing" if queued else "already queued", "repository": f"{owner}/{name}"}


@router.get(
    "/export/qa.jsonl",
    summary="Export the answers as JSONL, for evaluation",
    response_class=StreamingResponse,
    responses={
        **ADMIN_REQUIRED,
        200: {"description": "One JSON object a line.", "content": {"application/x-ndjson": {}}},
    },
    dependencies=[Depends(require_admin)],
)
def export_qa(
    db: Annotated[Session, Depends(get_db)],
    since: Annotated[datetime | None, Query(description="Only answers from then on.")] = None,
    limit: Annotated[int, Query(ge=1, le=100_000)] = 10_000,
) -> StreamingResponse:
    """Every logged answer, oldest first: `question`, `answer`, `state`, `confidence`,
    `mode`, `citations` (`ref`, `file`, `start_line`, `end_line`, `verified`) and the
    `sources` it was given: a ready-made evaluation set."""
    # Read now: the session closes before a streamed body would be.
    lines = list(qa_lines(db, since, limit))
    return StreamingResponse(
        iter(lines),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="atlas-qa.jsonl"'},
    )


@router.get(
    "/export/audit.md",
    summary="The knowledge audit as Markdown",
    response_class=PlainTextResponse,
    responses={200: {"content": {"text/markdown": {}}}},
)
def export_audit(db: Annotated[Session, Depends(get_db)]) -> PlainTextResponse:
    """What the AUDIT mode answers, as a report: the sources (kind, weight, files, when
    added), the knowledge health, and the latest weekly audit."""
    return PlainTextResponse(
        audit_markdown(db),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="atlas-audit.md"'},
    )
