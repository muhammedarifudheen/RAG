"""Caches for repeated work: whole answers to repeated questions, and the relevance
judge's scores. In memory, per server process, each entry kept for a day."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Generic, TypeVar

V = TypeVar("V")

DAY = 24 * 3600.0


class TTLCache(Generic[V]):
    """The `size` most recently used entries, each kept for `ttl` seconds."""

    def __init__(self, size: int, ttl: float = DAY, clock: Callable[[], float] = time.monotonic):
        self.size, self.ttl, self.clock = size, ttl, clock
        self._items: OrderedDict[str, tuple[float, V]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> V | None:
        with self._lock:
            found = self._items.get(key)
            if found is None:
                return None
            stored, value = found
            if self.clock() - stored > self.ttl:
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return value

    def put(self, key: str, value: V) -> None:
        with self._lock:
            self._items[key] = (self.clock(), value)
            self._items.move_to_end(key)
            while len(self._items) > self.size:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


def key_of(*parts: object) -> str:
    """A stable key for JSON-able parts."""
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def answer_cacheable(response: dict) -> bool:
    """Answers that stay right for a day: complete, from the knowledge base or general
    knowledge, not about current events and not using the web."""
    return (
        bool(response.get("complete"))
        and response.get("route") not in ("current", "image", "review", "vision")
        and not response.get("web_sources")
        and not response.get("images")
        and bool(response.get("answer", "").strip())
    )
