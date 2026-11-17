"""A zero-retrieval detector: a broken index is caught in minutes, not weeks.

Vector search returns the nearest excerpts however poor they are, so a query that retrieves
nothing is not a hard question: it is an empty index, a failed embedding or a failed search.
When more than a fifth of the last 100 queries retrieve nothing, the index is broken, and
a webhook says so (once, and again when it recovers).

One record per query (only queries that search the knowledge base): how many excerpts search
found, the best rerank score, how many reached the model, and the answer's state. They are
kept in memory, per server process, for the last `window` queries: nothing is written to the
database, and a restart starts the window afresh (the monitor reports "insufficient_data"
until it has `min_samples` queries, so a fresh server does not alarm).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.config import settings
from app.retrieval.gate import percentile

logger = logging.getLogger("atlas.retrieval")

# After an alert or a recovery, the next one waits this long, so a rate hovering at the
# threshold does not send a webhook a minute.
COOLDOWN_SECONDS = 300.0


@dataclass
class QueryRecord:
    chunks_retrieved: int  # what search found, before judging
    top_rerank_score: float | None  # the best score the reranker gave (the judge's 0-10)
    final_chunk_count: int  # what reached the model
    answer_state: str | None = None  # set when the answer is done
    at: float = field(default_factory=time.time)


def _notify(payload: dict) -> None:
    """The default notification: a `health` webhook, delivered in the background."""
    from app.services import webhooks

    webhooks.emit("health", payload)


class RetrievalMonitor:
    def __init__(
        self,
        window: int = 100,
        threshold: float = 0.20,
        min_samples: int = 10,
        notify: Callable[[dict], None] = _notify,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.window, self.threshold, self.min_samples = window, threshold, min_samples
        self.notify, self.clock = notify, clock
        self._records: deque[QueryRecord] = deque(maxlen=window)
        self._lock = threading.Lock()
        self._alerting = False
        self._last_sent: float | None = None
        self.last_alert_at: str | None = None

    # --- recording --------------------------------------------------------------------

    def record(
        self, chunks_retrieved: int, top_rerank_score: float | None, final_chunk_count: int
    ) -> QueryRecord:
        entry = QueryRecord(chunks_retrieved, top_rerank_score, final_chunk_count)
        with self._lock:
            self._records.append(entry)
            message = self._check_locked()
        if message is not None:
            self._send(message)
        return entry

    def finish(self, entry: QueryRecord, answer_state: str | None) -> None:
        """The answer is done: its state is kept, and the query's summary is logged."""
        with self._lock:
            entry.answer_state = answer_state
        logger.info(
            "retrieval_summary %s",
            json.dumps(
                {
                    "chunks_retrieved": entry.chunks_retrieved,
                    "top_rerank_score": entry.top_rerank_score,
                    "final_chunk_count": entry.final_chunk_count,
                    "answer_state": answer_state,
                }
            ),
        )

    # --- the verdict ------------------------------------------------------------------

    def _rate_locked(self) -> tuple[int, int]:
        empty = sum(1 for r in self._records if r.chunks_retrieved == 0)
        return empty, len(self._records)

    def _check_locked(self) -> dict | None:
        """The webhook payload if the rate has just crossed the threshold either way."""
        empty, total = self._rate_locked()
        if total < self.min_samples:
            return None
        alerting = empty / total > self.threshold
        if alerting == self._alerting:
            return None
        now = self.clock()
        if self._last_sent is not None and now - self._last_sent < COOLDOWN_SECONDS:
            return None  # crossed again too soon: say nothing, keep the old state
        self._alerting = alerting
        self._last_sent = now
        if alerting:
            self.last_alert_at = datetime.now(UTC).isoformat()
        return self._payload_locked("alert" if alerting else "recovered", empty, total)

    def _payload_locked(self, state: str, empty: int, total: int) -> dict:
        rate = empty / total
        scores = [r.top_rerank_score for r in self._records if r.top_rerank_score is not None]
        message = (
            f"{empty} of the last {total} queries retrieved nothing ({rate:.0%}, over "
            f"{self.threshold:.0%}): the index is likely broken."
            if state == "alert"
            else f"Empty retrievals are back to {rate:.0%} of the last {total} queries."
        )
        return {
            "check": "retrieval",
            "state": state,
            "empty_rate": round(rate, 3),
            "empty": empty,
            "queries": total,
            "threshold": self.threshold,
            "p50_top_rerank_score": round(percentile(scores, 50), 3) if scores else None,
            "message": message,
        }

    def _send(self, payload: dict) -> None:
        log = logger.error if payload["state"] == "alert" else logger.info
        log("retrieval health %s: %s", payload["state"], payload["message"])
        try:
            self.notify(payload)
        except Exception:
            logger.exception("the retrieval health webhook could not be sent")

    # --- for /health/retrieval --------------------------------------------------------

    def status(self) -> dict:
        with self._lock:
            empty, total = self._rate_locked()
            scores = [r.top_rerank_score for r in self._records if r.top_rerank_score is not None]
            states = Counter(r.answer_state or "pending" for r in self._records)
            enough = total >= self.min_samples
            rate = empty / total if total else None
            return {
                "window": self.window,
                "queries": total,
                "empty": empty,
                "empty_rate": round(rate, 4) if rate is not None else None,
                "p50_top_rerank_score": round(percentile(scores, 50), 3) if scores else None,
                "threshold": self.threshold,
                "min_samples": self.min_samples,
                "alert": bool(enough and rate is not None and rate > self.threshold),
                "state": (
                    "insufficient_data"
                    if not enough
                    else "alert"
                    if rate is not None and rate > self.threshold
                    else "ok"
                ),
                "last_alert_at": self.last_alert_at,
                "answer_states": dict(states),
            }


_monitor: RetrievalMonitor | None = None
_monitor_lock = threading.Lock()


def get_monitor() -> RetrievalMonitor:
    """The process-wide monitor, built on first use from the settings."""
    global _monitor
    with _monitor_lock:
        if _monitor is None:
            _monitor = RetrievalMonitor(
                window=settings.retrieval_alert_window,
                threshold=settings.retrieval_alert_threshold,
                min_samples=settings.retrieval_alert_min_samples,
            )
        return _monitor
