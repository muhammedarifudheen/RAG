from functools import cache
from threading import Lock
from typing import Protocol

from app.config import settings


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str) -> None:
        # Imported here because it pulls in torch, which takes seconds to load.
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)

    def embed(self, text: str) -> list[float]:
        vectors = self.model.encode([text], normalize_embeddings=True, show_progress_bar=False)
        return vectors[0].tolist()


_lock = Lock()


@cache
def _load() -> Embedder:
    return SentenceTransformerEmbedder(settings.embedding_model)


def get_embedder() -> Embedder:
    """The process-wide embedder, loaded on first use."""
    with _lock:  # concurrent first requests must not each load the model
        return _load()
