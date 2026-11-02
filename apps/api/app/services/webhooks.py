"""Webhooks: ingests, answers and gaps, posted as JSON to the addresses that want them.

Each delivery is signed: `X-Atlas-Signature-256: sha256=<HMAC-SHA256 of the body with the
webhook's secret>`, with `X-Atlas-Event` and a unique `X-Atlas-Delivery`. Deliveries run in
the background; a request never waits for one, and a failure never fails it. Addresses
come from the webhooks table (the admin adds them) and from ATLAS_WEBHOOKS, which survives
a redeploy of the free server's database."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from datetime import UTC, datetime

import httpx2
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Webhook

logger = logging.getLogger("atlas.webhooks")

EVENTS = ("ingest", "query", "gap")
TIMEOUT_SECONDS = 5.0
RETRY_AFTER_SECONDS = 2.0

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="webhook")


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def check_url(url: str) -> str:
    """The address if it is a public http(s) one; ValueError otherwise (no internal hosts:
    a webhook must not be a way into the server's network)."""
    from worker.fetch import FetchError, check_public_url

    try:
        return check_public_url(url)
    except FetchError as error:
        raise ValueError(str(error)) from error


def configured() -> list[str]:
    """The addresses in ATLAS_WEBHOOKS (comma-separated)."""
    return [u.strip() for u in (settings.atlas_webhooks or "").split(",") if u.strip()]


def _targets(db: Session | None, event: str) -> list[tuple[int | None, str, str]]:
    targets: list[tuple[int | None, str, str]] = [
        (None, url, settings.atlas_webhook_secret or "") for url in configured()
    ]
    try:
        if db is None:
            from app.db import SessionLocal

            with SessionLocal() as own:
                rows = own.scalars(select(Webhook)).all()
        else:
            rows = db.scalars(select(Webhook)).all()
        targets += [(w.id, w.url, w.secret) for w in rows if event in (w.events or EVENTS)]
    except Exception:
        logger.debug("no webhooks table", exc_info=True)
        if db is not None:
            with suppress(Exception):
                db.rollback()
    return targets


def emit(event: str, data: dict, db: Session | None = None) -> None:
    """Tells every webhook that wants `event` about it, in the background."""
    if event not in EVENTS:
        raise ValueError(event)
    targets = _targets(db, event)
    if not targets:
        return
    body = json.dumps(
        {
            "event": event,
            "id": str(uuid.uuid4()),
            "at": datetime.now(UTC).isoformat(),
            "data": data,
        },
        default=str,
    ).encode()
    for target in targets:
        _pool.submit(_deliver, event, body, *target)


def _deliver(event: str, body: bytes, webhook_id: int | None, url: str, secret: str) -> int:
    """Posts one delivery, once more after a moment if it fails; returns the status
    (0: not reached) and keeps it with the webhook."""
    status = 0
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Atlas-Webhook/1",
        "X-Atlas-Event": event,
        "X-Atlas-Delivery": json.loads(body)["id"],
        "X-Atlas-Signature-256": sign(secret, body),
    }
    for attempt in range(2):
        try:
            check_url(url)  # again: the name may now point somewhere else
            with httpx2.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
                status = client.post(url, content=body, headers=headers).status_code
        except (httpx2.HTTPError, ValueError) as error:
            logger.info("webhook %s: %s", url, error)
            status = 0
        if 200 <= status < 300 or 400 <= status < 500:
            break
        if attempt == 0:
            time.sleep(RETRY_AFTER_SECONDS)
    if webhook_id is not None:
        _note_status(webhook_id, status)
    return status


def _note_status(webhook_id: int, status: int) -> None:
    from app.db import SessionLocal

    try:
        with SessionLocal() as db:
            row = db.get(Webhook, webhook_id)
            if row is not None:
                row.last_status, row.last_at = status, datetime.now(UTC)
                db.commit()
    except Exception:
        logger.debug("could not note the webhook's status", exc_info=True)


def query_event(question: str, data: dict) -> dict:
    """What a `query` delivery says about an answer."""
    return {
        "question": question,
        "answer": data.get("answer"),
        "epistemic": data.get("epistemic"),
        "confidence": (data.get("confidence") or {}).get("level"),
        "mode": data.get("mode"),
        "footer": data.get("footer"),
        "citations": [c.get("ref") for c in data.get("citations") or [] if c.get("verified")],
    }
