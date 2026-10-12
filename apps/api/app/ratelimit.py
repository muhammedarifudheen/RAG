import math
import time
from collections import deque
from collections.abc import Callable
from threading import Lock

from fastapi import HTTPException, Request

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


def rate_limit(scope: str, limit: Callable[[], int]) -> Callable[[Request], None]:
    """A dependency enforcing `limit()` requests per minute per client IP within `scope`."""

    def dependency(request: Request) -> None:
        allowed = limit()
        if allowed <= 0:
            return
        # The socket peer, not X-Forwarded-For, which any client can set. Behind a
        # proxy, run uvicorn with --proxy-headers so this is the real client.
        client = request.client.host if request.client else "unknown"
        retry_after = limiter.check(f"{scope}:{client}", allowed)
        if retry_after is not None:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit of {allowed} requests per minute exceeded.",
                headers={"Retry-After": str(max(math.ceil(retry_after), 1))},
            )

    return dependency
