"""A cross-encoder reranker for /ask, behind ATLAS_RERANK=on (off by default).

bge-reranker-v2-m3 reads each (query, excerpt) pair together and scores how well the excerpt
answers the query: a better judge than similarity, and one model call instead of many.

Costs to know before turning it on:
- It is run with ONNX Runtime from the community export of the same weights, not with
  sentence-transformers: torch is not in the server image.
- The model is large: about 2.3 GB as fp32 and about 570 MB as int8. The public server's
  512 MB cannot hold either, and an out-of-memory kill is not something a fallback can catch.
  Turn it on only where the memory exists.
- On a CPU, scoring 20 pairs takes seconds, not the 150 ms default timeout (which is the
  spec's, for a GPU). Within the timeout the stage degrades to the RRF order every time;
  raise ATLAS_RERANK_TIMEOUT_MS to see its effect.
"""

from __future__ import annotations

import logging
import math
import statistics
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence

from app.config import settings
from app.retrieval.budget import Trace, run_stage
from app.schemas import CodeChunk

logger = logging.getLogger("atlas.retrieval")

# Candidates the reranker reads, and excerpts it keeps.
CANDIDATES = 20
KEEP = 5

_FILES = {
    "fp32": ("onnx/model.onnx", "onnx/model.onnx_data"),
    "int8": ("onnx/model_int8.onnx",),
}


class RerankDeadline(Exception):
    """The rerank's wall-clock budget ran out: raised between batches, so the abandoned work
    stops instead of carrying on in the background."""


class OnnxCrossEncoder:
    """CrossEncoder.predict(pairs) -> one score per (query, passage), on the CPU."""

    accepts_deadline = True  # predict takes `deadline` and `batches`, as rerank() uses them

    def __init__(self, repo: str, precision: str, max_length: int = 512, batch_size: int = 8):
        import onnxruntime
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        files = [hf_hub_download(repo, name) for name in _FILES[precision]]
        self.batch_size = batch_size
        self.tokenizer = Tokenizer.from_file(hf_hub_download(repo, "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=max_length)
        self.tokenizer.enable_padding()
        options = onnxruntime.SessionOptions()
        options.enable_mem_pattern = False  # batches vary in length; patterns only add memory
        self.session = onnxruntime.InferenceSession(
            files[0], options, providers=["CPUExecutionProvider"]
        )
        self.inputs = {i.name for i in self.session.get_inputs()}
        self.provider = self.session.get_providers()[0]  # the one actually granted

    def predict(
        self,
        pairs: Sequence[tuple[str, str]],
        *,
        deadline: float | None = None,
        batches: list[int] | None = None,
    ) -> list[float]:
        """Scores in batches of `batch_size`. Past `deadline` (a time.monotonic() value) it
        stops before the next batch; `batches` collects the size of each batch run."""
        import numpy as np

        scores: list[float] = []
        for start in range(0, len(pairs), self.batch_size):
            if deadline is not None and time.monotonic() >= deadline:
                raise RerankDeadline("the rerank deadline passed")
            encoded = self.tokenizer.encode_batch(list(pairs[start : start + self.batch_size]))
            feeds = {
                "input_ids": np.array([e.ids for e in encoded], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in encoded], dtype=np.int64),
            }
            feeds = {k: v for k, v in feeds.items() if k in self.inputs}
            scores.extend(float(x) for x in self.session.run(None, feeds)[0].reshape(-1))
            if batches is not None:
                batches.append(len(encoded))
        return scores


_lock = threading.Lock()
# Held while a rerank runs. One that overran its budget is still running when the next query
# arrives; that query goes without the reranker rather than stacking a second one on the CPU.
_busy = threading.Lock()
_model: object | None = None  # anything with predict(pairs) -> scores
_failure: str | None = None  # why it could not load
_loading = False
_load_ms: float | None = None
_warmup_ms: float | None = None
_provider: str | None = None
# Latencies of the last real reranks, in milliseconds, newest last.
WINDOW = 20
_latencies: deque[float] = deque(maxlen=WINDOW)
_slow_streak = 0
_disabled_reason: str | None = None  # set when the health rule flipped ATLAS_RERANK off

# What the warm-up predicts on: a batch the size of the real one, passages of real length.
WARMUP_PAIRS = [
    ("how does the signer verify a signature?", "def verify_signature(self, value, sig): " * 20)
] * 8


def enabled() -> bool:
    return settings.atlas_rerank.lower() == "on"


def _load() -> None:
    """Loads the model, then runs it on dummy pairs `atlas_rerank_warmup_runs` times, and logs
    how long each took. Whatever goes wrong, the service carries on with ATLAS_RERANK off."""
    global _model, _failure, _loading, _load_ms, _warmup_ms, _provider
    try:
        started = time.perf_counter()
        model = OnnxCrossEncoder(
            settings.atlas_rerank_onnx_repo,
            settings.atlas_rerank_precision,
            settings.atlas_rerank_max_length,
        )
        loaded = time.perf_counter()
        for _ in range(settings.atlas_rerank_warmup_runs):
            model.predict(WARMUP_PAIRS)  # type: ignore[attr-defined]
        warmed = time.perf_counter()
        with _lock:
            _model, _failure = model, None
            _load_ms = (loaded - started) * 1000
            _warmup_ms = (warmed - loaded) * 1000
            _provider = getattr(model, "provider", None)
        logger.info(
            "reranker ready: load_ms=%d warmup_ms=%d warmup_runs=%d provider=%s model=%s (%s)",
            _load_ms,
            _warmup_ms,
            settings.atlas_rerank_warmup_runs,
            _provider,
            settings.atlas_rerank_model,
            settings.atlas_rerank_precision,
        )
    except Exception as error:  # a missing package, no network, no memory: all the same here
        reason = f"{type(error).__name__}: {str(error)[:120]}"
        logger.warning(
            "reranker failed to load (%s); ATLAS_RERANK stays off", reason, exc_info=True
        )
        with _lock:
            _failure = reason
        settings.atlas_rerank = "off"  # nothing will try to use a model that is not there
    finally:
        with _lock:
            _loading = False


def start_loading() -> None:
    """Loads the model once, in the background, when the flag is on. Safe to call twice."""
    global _loading
    if not enabled():
        return
    with _lock:
        if _model is not None or _loading:
            return
        _loading = True
    threading.Thread(target=_load, name="reranker-load", daemon=True).start()


def get() -> tuple[object | None, str | None]:
    """The loaded model, or None and why not (still loading, or the load failed)."""
    with _lock:
        if _model is not None:
            return _model, None
        if _failure:
            return None, f"reranker failed to load ({_failure})"
        return None, "reranker still loading"


def p50_ms() -> float | None:
    """The median latency of the last 20 real reranks, or None before there are any."""
    with _lock:
        return statistics.median(_latencies) if _latencies else None


def record(ms: float) -> None:
    """Notes one real rerank's latency. If the median of the last 20 has been over the limit for
    `atlas_rerank_slow_streak` queries running, the reranker is switched off."""
    global _slow_streak
    with _lock:
        _latencies.append(ms)
        median = statistics.median(_latencies)
        _slow_streak = _slow_streak + 1 if median > settings.atlas_rerank_p50_limit_ms else 0
        flip = _slow_streak >= settings.atlas_rerank_slow_streak and enabled()
        streak = _slow_streak
    if flip:
        _switch_off(median, streak)


def _switch_off(median: float, streak: int) -> None:
    """Flips ATLAS_RERANK to off (until the server restarts) and tells the webhooks."""
    global _disabled_reason, _slow_streak
    reason = (
        f"median rerank latency {median:.0f} ms over {settings.atlas_rerank_p50_limit_ms:.0f} ms "
        f"for {streak} queries in a row"
    )
    with _lock:
        _disabled_reason = reason
        _slow_streak = 0
    settings.atlas_rerank = "off"
    logger.warning("reranker switched off: %s", reason)
    try:
        from app.services.webhooks import emit

        # The `health` webhook event, typed health.degraded in its data.
        emit(
            "health",
            {
                "type": "health.degraded",
                "component": "reranker",
                "reason": reason,
                "p50_ms": round(median, 1),
                "limit_ms": settings.atlas_rerank_p50_limit_ms,
                "consecutive_queries": streak,
                "action": "ATLAS_RERANK set to off until the server restarts",
            },
        )
    except Exception:  # a webhook problem must never reach a query
        logger.warning("could not send the health.degraded webhook", exc_info=True)


def status() -> dict:
    """For /health/reranker: whether it is loaded and on what, and how fast it has been."""
    with _lock:
        loaded = _model is not None
        median = statistics.median(_latencies) if _latencies else None
        if _disabled_reason:
            state, reason = "disabled", _disabled_reason
        elif _failure:
            state, reason = "failed", _failure
        elif _loading:
            state, reason = "loading", None
        elif loaded and enabled():
            state, reason = "ready", None
        else:
            state, reason = "off", None
        return {
            "loaded": loaded,
            "provider": _provider if loaded else None,
            "p50_ms": round(median, 1) if median is not None else None,
            "enabled": enabled(),
            "state": state,
            "samples": len(_latencies),
            "load_ms": round(_load_ms, 1) if _load_ms is not None else None,
            "warmup_ms": round(_warmup_ms, 1) if _warmup_ms is not None else None,
            "reason": reason,
        }


def reset() -> None:
    """Forgets everything (for tests)."""
    global _model, _failure, _loading, _load_ms, _warmup_ms, _provider, _slow_streak
    global _disabled_reason, _busy
    _busy = threading.Lock()
    with _lock:
        _model = _failure = _load_ms = _warmup_ms = _provider = _disabled_reason = None
        _loading = False
        _slow_streak = 0
        _latencies.clear()


def passage(chunk: CodeChunk) -> str:
    """The text the reranker reads for an excerpt: what it is, where, then its content."""
    return f"{chunk.name} ({chunk.file})\n{chunk.snippet}"


def sigmoid(logit: float) -> float:
    return 1 / (1 + math.exp(-max(min(logit, 50.0), -50.0)))


def rerank(
    trace: Trace,
    query: str,
    chunks: Sequence[CodeChunk],
    keep: int = KEEP,
    timeout: float | None = None,
    model_source: Callable[[], tuple[object | None, str | None]] | None = None,
) -> list[CodeChunk]:
    """The top `keep` of `chunks` ordered by the cross-encoder, each with its `rerank_score`
    (the model's raw logit), scored in batches within a hard wall-clock timeout
    (`ATLAS_RERANK_TIMEOUT_MS`). On a timeout or an error, or if the model is busy with an
    earlier overrun or not loaded, the first `keep` in their given (RRF) order, the answer
    marked degraded and `trace.reason_code` set: "rerank_timeout" for a timeout, an error or a
    busy model, "rerank_unavailable" for a model that is not loaded. The cost of the stage
    is left in `trace.extra["rerank"]` for the query log."""
    candidates = list(chunks[:CANDIDATES])
    if len(candidates) < 2:
        return candidates[:keep]
    model, why = (model_source or get)()  # resolved now, so tests can patch `get`
    if model is None:
        trace.degrade(f"{why}; used the RRF order")
        trace.reason_code = "rerank_unavailable"
        return candidates[:keep]
    busy = _busy  # this exact lock is released, even if a test or reset replaces the global
    if not busy.acquire(blocking=False):
        trace.degrade("reranker still busy with an earlier query; used the RRF order")
        trace.reason_code = "rerank_timeout"
        trace.timed_out.add("rerank")
        trace.extra["rerank"] = {
            "rerank_ms": 0.0,
            "rerank_batches": 0,
            "rerank_timed_out": True,
            "rerank_busy": True,
        }
        return candidates[:keep]
    seconds = settings.atlas_rerank_timeout_ms / 1000 if timeout is None else timeout
    pairs = [(query, passage(c)) for c in candidates]
    batches: list[int] = []
    started = time.perf_counter()
    deadline = time.monotonic() + seconds

    def work() -> list[float]:
        try:
            if getattr(model, "accepts_deadline", False):
                return model.predict(pairs, deadline=deadline, batches=batches)  # type: ignore[attr-defined]
            result = model.predict(pairs)  # type: ignore[attr-defined]
            size = getattr(model, "batch_size", 8)
            batches.extend(min(size, len(pairs) - i) for i in range(0, len(pairs), size))
            return result
        finally:
            busy.release()

    scores = run_stage(
        trace,
        "rerank",
        work,
        None,
        seconds,
        reason=f"reranker over its {round(seconds * 1000)} ms; used the RRF order",
    )
    elapsed = (time.perf_counter() - started) * 1000
    timed_out = "rerank" in trace.timed_out
    trace.extra["rerank"] = {
        "rerank_ms": round(elapsed, 1),
        "rerank_batches": len(batches),
        "rerank_timed_out": timed_out,
        "rerank_candidates": len(candidates),
    }
    # A real rerank's latency, for the health rule: its time if it answered, the budget if it
    # overran it; not the instant failure of a broken model, which says nothing about speed.
    if scores is not None or timed_out:
        record(elapsed)
    if scores is None or len(scores) != len(candidates):
        trace.reason_code = "rerank_timeout"
        if scores is not None:
            trace.degrade("reranker returned the wrong number of scores; used the RRF order")
        return candidates[:keep]
    scored = [
        c.model_copy(update={"rerank_score": round(s, 4)}) for c, s in zip(candidates, scores)
    ]
    scored.sort(key=lambda c: -(c.rerank_score or 0.0))  # stable: ties keep the RRF order
    return scored[:keep]
