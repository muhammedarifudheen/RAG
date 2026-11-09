"""Stage budgets: a stage that is too slow or fails gives way to its fallback, and the answer
says so ("degraded") instead of failing or silently waiting."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from typing import TypeVar

T = TypeVar("T")

logger = logging.getLogger("atlas.retrieval")

# Stages run on their own threads so a slow one can be left behind. Daemon-like: the pool
# is never joined; a stage that overruns finishes (or fails) in the background.
_POOL = ThreadPoolExecutor(max_workers=16, thread_name_prefix="retrieval-stage")


@dataclass
class Trace:
    """What happened in one query's retrieval: seconds per stage, the reasons it degraded."""

    timings: dict[str, float] = field(default_factory=dict)
    degraded: list[str] = field(default_factory=list)
    cache_hits: list[str] = field(default_factory=list)

    def degrade(self, reason: str) -> None:
        if reason not in self.degraded:
            self.degraded.append(reason)

    @property
    def is_degraded(self) -> bool:
        return bool(self.degraded)


def run_stage(
    trace: Trace,
    name: str,
    work: Callable[[], T],
    fallback: T,
    budget: float | None,
    *,
    reason: str | None = None,
) -> T:
    """Runs `work` and returns its result, or `fallback` if it takes longer than `budget`
    seconds (None: no limit) or raises. Either way the trace records the stage's time, and
    on a fallback the reason it degraded (default: "<name> timed out" or "<name> failed")."""
    started = time.monotonic()
    try:
        if budget is None:
            return work()
        return _POOL.submit(work).result(timeout=budget)
    except FutureTimeout:
        trace.degrade(reason or f"{name} timed out")
        logger.warning("stage %s over its %.1fs budget; using its fallback", name, budget)
        return fallback
    except Exception:
        trace.degrade(reason or f"{name} failed")
        logger.exception("stage %s failed; using its fallback", name)
        return fallback
    finally:
        trace.timings[name] = round(time.monotonic() - started, 3)


def timed(trace: Trace, name: str):
    """A context manager recording a stage's time, for work that has no fallback."""

    class _Timer:
        def __enter__(self):
            self.started = time.monotonic()

        def __exit__(self, *_):
            trace.timings[name] = round(time.monotonic() - self.started, 3)

    return _Timer()
