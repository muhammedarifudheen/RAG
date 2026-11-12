"""What retrieval remembers between questions: the knowledge base's version, a cache of
retrievals, and each source's track record. In memory, per server process."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.assistant.cache import TTLCache, key_of
from app.models import Source
from app.models.knowledge import AnswerLog
from app.retrieval.scoring import smoothed_hit_rate
from app.schemas import CodeChunk

HOUR = 3600.0

# Retrievals of a query under its filters, for an hour, and never across a knowledge-base
# version: the version is in the key, so an ingest makes every older entry unreachable.
RETRIEVALS: TTLCache[tuple[list[CodeChunk], str | None]] = TTLCache(512, ttl=HOUR)

_version_lock = threading.Lock()
_bumps = 0
_seen: tuple[float, str] | None = None
VERSION_TTL = 2.0  # seconds a computed version is reused: one query's worth of calls


def bump() -> None:
    """Call after any change to the knowledge base the database cannot show by itself."""
    global _bumps, _seen
    with _version_lock:
        _bumps += 1
        _seen = None
    RETRIEVALS.clear()


def kb_version(db: Session) -> str:
    """A fingerprint of the knowledge base: its sources and their versions. It changes on any
    ingest, re-ingest or removal, so no cache serves a stale one."""
    global _seen
    now = time.monotonic()
    with _version_lock:
        if _seen is not None and now - _seen[0] < VERSION_TTL:
            return _seen[1]
        bumps = _bumps
    count, newest, created, versions, updated = db.execute(
        select(
            func.count(Source.id),
            func.max(Source.id),
            func.max(Source.created_at),
            func.coalesce(func.sum(Source.version), 0),
            func.max(Source.source_updated_at),
        )
    ).one()
    version = key_of(count, newest, created, versions, updated, bumps)[:16]
    with _version_lock:
        if bumps == _bumps:  # a bump during the query makes this reading stale
            _seen = (now, version)
    return version


def retrieval_key(query: str, limit: int, as_of: datetime | None, version: str) -> str:
    return key_of(" ".join(query.lower().split()), limit, as_of, version)


_rates: tuple[float, dict[int, float]] | None = None
_rates_lock = threading.Lock()
RATES_TTL = 600.0
RATES_WINDOW_DAYS = 90


def cached_hit_rates() -> dict[int, float]:
    """The source hit rates if they are cached, else none (neutral). Never touches the database,
    so it is safe in the request path."""
    with _rates_lock:
        return _rates[1] if _rates is not None else {}


def source_hit_rates(db: Session) -> dict[int, float]:
    """Each source's historical precision, from the thumbs on answers that used it
    (smoothed; a source with no votes is absent, which ranking reads as neutral). Kept for
    ten minutes."""
    global _rates
    now = time.monotonic()
    with _rates_lock:
        if _rates is not None and now - _rates[0] < RATES_TTL:
            return _rates[1]
    since = datetime.now(UTC) - timedelta(days=RATES_WINDOW_DAYS)
    titles = {title: sid for sid, title in db.execute(select(Source.id, Source.title))}
    votes: dict[int, list[int]] = {}
    rows = db.execute(
        select(AnswerLog.feedback, AnswerLog.sources)
        .where(AnswerLog.feedback.is_not(None), AnswerLog.created_at >= since)
        .limit(5000)
    )
    for feedback, sources in rows:
        for title in {s.get("title") for s in sources or [] if isinstance(s, dict)}:
            sid = titles.get(title)
            if sid is not None:
                votes.setdefault(sid, [0, 0])[0 if feedback > 0 else 1] += 1
    rates = {sid: smoothed_hit_rate(up, down) for sid, (up, down) in votes.items()}
    with _rates_lock:
        _rates = (now, rates)
    return rates
