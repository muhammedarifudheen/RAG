"""A cross-encoder reranker for the eval harness: take the top candidates a search returned,
score each (question, excerpt) pair, and reorder them before they are scored.

It runs on the machine running the eval, not on the Atlas server, so its latency is that of
this machine (and the server's free 512 MB plan could not hold the model at all). It needs
`torch` and `transformers`, imported only when a reranker is asked for.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

DEFAULT_MODEL = "BAAI/bge-reranker-v2-m3"


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
