from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

from worker.extract.types import MODULE, Symbol

# all-MiniLM-L6-v2 truncates input at 256 word pieces, so more text than this is discarded.
MAX_CHARS = 2000


class Embedder(Protocol):
    def encode(
        self, texts: Sequence[str], on_progress: Callable[[int, int], None] | None = None
    ) -> list[list[float]]: ...


def symbol_text(symbol: Symbol) -> str:
    """The text embedded for a symbol: what it is, where it lives, and its source."""
    header = f"{symbol.kind} {symbol.name}"
    if symbol.kind != MODULE:
        header += f" in {symbol.path}"
    return f"{header}\n{symbol.text[:MAX_CHARS]}"


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str, batch_size: int = 64) -> None:
        # Imported here because it pulls in torch, which takes seconds to load.
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)
        self.batch_size = batch_size

    def encode(
        self, texts: Sequence[str], on_progress: Callable[[int, int], None] | None = None
    ) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start : start + self.batch_size])
            encoded = self.model.encode(
                batch,
                batch_size=self.batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            vectors.extend(encoded.tolist())
            if on_progress is not None:
                on_progress(len(vectors), len(texts))
        return vectors
