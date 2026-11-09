"""A cross-encoder reranker for the eval harness: take the top candidates a search returned,
score each (question, excerpt) pair, and reorder them before they are scored.

It runs on the machine running the eval, not on the Atlas server, so its latency is that of
this machine (and the server's free 512 MB plan could not hold the model at all). It needs
`torch` and `transformers` (or, without them, `onnxruntime`, `tokenizers` and `huggingface_hub`
for the ONNX export), imported only when a reranker is asked for.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import ClassVar

DEFAULT_MODEL = "BAAI/bge-reranker-v2-m3"
# The same weights exported to ONNX, for machines where torch will not load.
ONNX_REPO = "onnx-community/bge-reranker-v2-m3-ONNX"


def reorder(chunks: Sequence[dict], scores: Sequence[float]) -> list[dict]:
    """`chunks` sorted by `scores`, best first; ties keep their original order."""
    order = sorted(range(len(chunks)), key=lambda i: (-scores[i], i))
    return [chunks[i] for i in order]


def passage(chunk: dict) -> str:
    """The text the reranker reads for an excerpt: what it is, where, then its code or prose."""
    return f"{chunk.get('name', '')} ({chunk.get('file', '')})\n{chunk.get('snippet', '')}"


def rerank_top(
    question: str,
    chunks: Sequence[dict],
    score: Callable[[str, list[str]], list[float]],
    top: int = 20,
) -> list[dict]:
    """The first `top` chunks reordered by `score(question, passages)`; the rest follow in
    their original order."""
    head, tail = list(chunks[:top]), list(chunks[top:])
    if len(head) < 2:
        return head + tail
    scores = score(question, [passage(c) for c in head])
    return reorder(head, scores) + tail


class CrossEncoderReranker:
    """A Hugging Face sequence-classification reranker (bge-reranker-v2-m3 and kin)."""

    def __init__(self, model: str = DEFAULT_MODEL, max_length: int = 512, batch_size: int = 8):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.torch = torch
        self.max_length = max_length
        self.batch_size = batch_size
        self.tokenizer = AutoTokenizer.from_pretrained(model)
        self.model = AutoModelForSequenceClassification.from_pretrained(model).eval()

    def __call__(self, question: str, passages: list[str]) -> list[float]:
        scores: list[float] = []
        with self.torch.no_grad():
            for start in range(0, len(passages), self.batch_size):
                batch = passages[start : start + self.batch_size]
                encoded = self.tokenizer(
                    [question] * len(batch),
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=self.max_length,
                    return_tensors="pt",
                )
                scores.extend(self.model(**encoded).logits.view(-1).float().tolist())
        return scores


class OnnxReranker:
    """The same reranker run with ONNX Runtime on the CPU (no torch). Reads the ONNX export of
    BAAI/bge-reranker-v2-m3; `precision` picks the file: "fp32" (the original weights) or
    "int8" (smaller and faster, with slightly different scores)."""

    FILES: ClassVar[dict[str, tuple[str, ...]]] = {
        "fp32": ("onnx/model.onnx", "onnx/model.onnx_data"),
        "int8": ("onnx/model_int8.onnx",),
    }

    def __init__(self, max_length: int = 512, batch_size: int = 8, precision: str = "fp32"):
        import onnxruntime
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        paths = [hf_hub_download(ONNX_REPO, name) for name in self.FILES[precision]]
        self.batch_size = batch_size
        self.tokenizer = Tokenizer.from_file(hf_hub_download(ONNX_REPO, "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=max_length)
        self.tokenizer.enable_padding()
        self.session = onnxruntime.InferenceSession(paths[0], providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.session.get_inputs()}

    def __call__(self, question: str, passages: list[str]) -> list[float]:
        import numpy as np

        scores: list[float] = []
        for start in range(0, len(passages), self.batch_size):
            pairs = [(question, text) for text in passages[start : start + self.batch_size]]
            encoded = self.tokenizer.encode_batch(pairs)
            feeds = {
                "input_ids": np.array([e.ids for e in encoded], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in encoded], dtype=np.int64),
            }
            feeds = {k: v for k, v in feeds.items() if k in self.inputs}
            scores.extend(float(x) for x in self.session.run(None, feeds)[0].reshape(-1))
        return scores


def make_reranker(model: str = DEFAULT_MODEL, max_length: int = 512, backend: str = "auto"):
    """A reranker: torch if it loads (or is asked for), else the ONNX export of the default
    model. Raises if neither can run."""
    if backend in ("auto", "torch"):
        try:
            return CrossEncoderReranker(model, max_length)
        except (ImportError, OSError) as error:
            if backend == "torch":
                raise
            print(f"torch is not usable here ({type(error).__name__}); using ONNX Runtime")
    if model != DEFAULT_MODEL:
        raise SystemExit(f"Only {DEFAULT_MODEL} has an ONNX fallback; {model} needs torch.")
    return OnnxReranker(max_length, precision="int8" if backend == "onnx-int8" else "fp32")
