import math
import time
from collections import deque
from collections.abc import Callable
from threading import Lock

from fastapi import HTTPException, Request

from app.config import settings

WINDOW_SECONDS = 60.0


class RateLimiter:
    """Sliding-window limiter held in process memory.

    Counts are per process: with several workers each one enforces the limit
    separately. Move the counters to a shared store before relying on exact limits.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = Lock()

    def check(self, key: str, limit: int, window: float = WINDOW_SECONDS) -> float | None:
        """Records a hit. Returns None if allowed, else the seconds until a retry can succeed."""
        now = self._clock()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - window:
                hits.popleft()
            if len(hits) >= limit:
                return hits[0] + window - now
            hits.append(now)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


_keys: dict[str, tuple[float, tuple[int, str] | None]] = {}


def identify_key(request: Request) -> tuple[int, str] | None:
    """(id, scope) of the API key a request carries in X-Atlas-Key, or None without one.
    An unknown or revoked key is refused. Looked up once a minute per key."""
    supplied = request.headers.get("x-atlas-key")
    if not supplied:
        return None
    from sqlalchemy import select

    from app.admin import key_hash
    from app.db import SessionLocal
    from app.models import ApiKey

    digest = key_hash(supplied)
    now = time.monotonic()
    cached = _keys.get(digest)
    if cached is None or now - cached[0] > WINDOW_SECONDS:
        try:
            with SessionLocal() as db:
                row = db.scalars(select(ApiKey).where(ApiKey.key_hash == digest)).first()
                found = (row.id, row.scope) if row is not None and not row.revoked else None
        except Exception:  # noqa: BLE001 - no database: no keys
            found = None
        _keys[digest] = (now, found)
        cached = _keys[digest]
    if cached[1] is None:
        raise HTTPException(401, "That API key is not valid.")
    return cached[1]


def require_write_key(request: Request) -> None:
    """A read-only API key may not write (share chats)."""
    caller = identify_key(request)
    if caller is not None and caller[1] != "write":
        raise HTTPException(403, "This API key can only read.")


def rate_limit(scope: str, limit: Callable[[], int]) -> Callable[[Request], None]:
    """A dependency enforcing `limit()` requests per minute per client IP within `scope`."""

    def dependency(request: Request) -> None:
        allowed = limit()
        if allowed <= 0:
            return
        # The socket peer, not X-Forwarded-For, which any client can set. Behind a
        # proxy, run uvicorn with --proxy-headers so this is the real client.
        client = request.client.host if request.client else "unknown"
        # An API key is its own caller, with its own limit.
        caller = identify_key(request)
        if caller is not None:
            client, allowed = f"key:{caller[0]}", settings.api_key_rate_limit_per_minute
        retry_after = limiter.check(f"{scope}:{client}", allowed)
        if retry_after is not None:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit of {allowed} requests per minute exceeded.",
                headers={"Retry-After": str(max(math.ceil(retry_after), 1))},
            )

    return dependency
