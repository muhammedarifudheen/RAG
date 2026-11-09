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
import threading
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


class OnnxCrossEncoder:
    """CrossEncoder.predict(pairs) -> one score per (query, passage), on the CPU."""

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

    def predict(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        import numpy as np

        scores: list[float] = []
        for start in range(0, len(pairs), self.batch_size):
            encoded = self.tokenizer.encode_batch(list(pairs[start : start + self.batch_size]))
            feeds = {
                "input_ids": np.array([e.ids for e in encoded], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in encoded], dtype=np.int64),
            }
            feeds = {k: v for k, v in feeds.items() if k in self.inputs}
            scores.extend(float(x) for x in self.session.run(None, feeds)[0].reshape(-1))
        return scores


_lock = threading.Lock()
_model: object | None = None  # anything with predict(pairs) -> scores
_failure: str | None = None  # why it could not load
_loading = False


def enabled() -> bool:
    return settings.atlas_rerank.lower() == "on"


def _load() -> None:
    global _model, _failure, _loading
    try:
        model = OnnxCrossEncoder(
            settings.atlas_rerank_onnx_repo,
            settings.atlas_rerank_precision,
            settings.atlas_rerank_max_length,
        )
        with _lock:
            _model, _failure = model, None
        logger.info(
            "reranker loaded: %s (%s)", settings.atlas_rerank_model, settings.atlas_rerank_precision
        )
    except Exception as error:  # a missing package, no network, no memory: all the same here
        logger.exception("reranker failed to load")
        with _lock:
            _failure = f"{type(error).__name__}: {str(error)[:120]}"
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
    (the model's raw logit). If the model is not loaded, fails or overruns the timeout, the
    first `keep` in their given (RRF) order and the answer is marked degraded."""
    candidates = list(chunks[:CANDIDATES])
    if len(candidates) < 2:
        return candidates[:keep]
    model, why = (model_source or get)()  # resolved now, so tests can patch `get`
    if model is None:
        trace.degrade(f"{why}; used the RRF order")
        return candidates[:keep]
    seconds = settings.atlas_rerank_timeout_ms / 1000 if timeout is None else timeout
    scores = run_stage(
        trace,
        "rerank",
        lambda: model.predict([(query, passage(c)) for c in candidates]),  # type: ignore[attr-defined]
        None,
        seconds,
        reason=f"reranker over its {round(seconds * 1000)} ms; used the RRF order",
    )
    if scores is None or len(scores) != len(candidates):
        if scores is not None:
            trace.degrade("reranker returned the wrong number of scores; used the RRF order")
        return candidates[:keep]
    scored = [
        c.model_copy(update={"rerank_score": round(s, 4)}) for c, s in zip(candidates, scores)
    ]
    scored.sort(key=lambda c: -(c.rerank_score or 0.0))  # stable: ties keep the RRF order
    return scored[:keep]
