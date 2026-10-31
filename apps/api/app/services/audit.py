"""The audit trail: append-only events for answers (hashes, retrieved ids, timings),
security events (refused injections, redactions, failed unlocks) and admin actions."""

from __future__ import annotations

import hashlib
import logging
from contextlib import suppress

from sqlalchemy.orm import Session

from app.models import AuditEvent

logger = logging.getLogger("atlas.api.audit")


def text_hash(text: str | None) -> str | None:
    return hashlib.sha256(text.encode()).hexdigest()[:24] if text else None


def record(db: Session | None, kind: str, actor: str | None, detail: dict) -> None:
    """Appends one event. Never raises: the request matters more than its audit line,
    which also goes to the log."""
    logger.info("audit %s actor=%s %s", kind, actor, detail)
    if db is None:
        return
    try:
        db.add(AuditEvent(kind=kind, actor=actor, detail=detail))
        db.commit()
    except Exception:
        logger.exception("could not write the audit event")
        with suppress(Exception):
            db.rollback()


def answer_event(question: str, data: dict) -> dict:
    """What an answer's audit event holds: hashes and ids, never the text."""
    return {
        "query": text_hash(question),
        "answer": text_hash(data.get("answer")),
        "retrieved": [c.get("symbol_id") for c in data.get("chunks") or []],
        "state": data.get("epistemic"),
        "timings": data.get("timings"),
        "redacted": data.get("redacted") or [],
    }
