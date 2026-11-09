"""Stage budgets: a stage that is too slow or fails gives way to its fallback, and the answer
says so ("degraded") instead of failing or silently waiting."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TypeVar

from app.config import settings

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
    timed_out: set[str] = field(default_factory=set)  # stages that overran their budget
    # A short code for the main reason it degraded (e.g. "rerank_timeout"), for the response.
    reason_code: str | None = None
    # Per-stage details for the query log, e.g. extra["rerank"] = {"rerank_ms": ...}.
    extra: dict[str, dict] = field(default_factory=dict)

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
        trace.timed_out.add(name)
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


# The pipeline's stages, in the order a query meets them.
STAGES = (
    "rewrite",
    "embed",
    "bm25",
    "vector",
    "fuse",
    "rerank",
    "assemble",
    "first_token",
    "full_answer",
)
# What enforcement can skip once an earlier stage has breached: the query planner's extra
# searches and the reranker (the relevance judge or the cross-encoder). Everything else is
# needed to answer at all.
OPTIONAL = ("rewrite", "rerank")


def parse_enforce(text: str | None) -> frozenset[str]:
    """The stages named in BUDGET_ENFORCE: "" or "off": none; "all": every stage; otherwise a
    comma-separated list. Unknown names are ignored, with a warning."""
    names = {n.strip().lower() for n in (text or "").split(",") if n.strip()}
    if names & {"off", "none"}:
        return frozenset()
    if "all" in names:
        return frozenset(STAGES)
    unknown = names - set(STAGES)
    if unknown:
        logger.warning("BUDGET_ENFORCE names unknown stages: %s", ", ".join(sorted(unknown)))
    return frozenset(names & set(STAGES))


class Budget:
    """One query's stage times against the latency budget.

    `record(stage, ms)` adds a stage's time (a stage can run more than once: each planned search
    embeds and searches) and notes a breach when a single run is over the stage's limit. In
    observe mode that is all it does. For a stage named in the enforce list, `skip_optional()`
    turns true, and the caller leaves out the optional stages that remain."""

    def __init__(self, enforce: str | None = None, limits: dict[str, float] | None = None):
        self.enforce = parse_enforce(settings.budget_enforce if enforce is None else enforce)
        self.limits = limits or {s: float(getattr(settings, f"budget_{s}_ms")) for s in STAGES}
        self.stage_ms: dict[str, float] = {}
        self.breached: list[str] = []  # in the order they happened

    def record(self, stage: str, ms: float) -> None:
        self.stage_ms[stage] = self.stage_ms.get(stage, 0.0) + ms
        if ms > self.limits[stage] and stage not in self.breached:
            self.breached.append(stage)

    @property
    def first_breach(self) -> str | None:
        return self.breached[0] if self.breached else None

    @property
    def enforced_breaches(self) -> list[str]:
        return [s for s in self.breached if s in self.enforce]

    def skip_optional(self) -> bool:
        """True once a stage that is being enforced has breached."""
        return bool(self.enforced_breaches)

    def snapshot(self) -> dict[str, float]:
        return {s: round(self.stage_ms[s], 1) for s in STAGES if s in self.stage_ms}

    def degrade_reasons(self) -> list[str]:
        return [f"latency budget: {s} over {self.limits[s]:.0f} ms" for s in self.enforced_breaches]


@contextmanager
def stage_timer(budget: Budget | None, stage: str) -> Iterator[None]:
    """Times the block and records it against `budget` (a no-op without one)."""
    started = time.perf_counter()
    try:
        yield
    finally:
        if budget is not None:
            budget.record(stage, (time.perf_counter() - started) * 1000)
