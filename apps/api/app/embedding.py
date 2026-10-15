from functools import cache
from threading import Lock
from typing import Protocol

from worker.embed import load_model

from app.config import settings


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...


class LocalEmbedder:
    def __init__(self, model_name: str) -> None:
        # The same copy the ingest pipeline uses, so the model is in memory once.
        self.model = load_model(model_name)

    def embed(self, text: str) -> list[float]:
        return self.model.encode([text])[0].tolist()


_lock = Lock()


@cache
def _load() -> Embedder:
    return LocalEmbedder(settings.embedding_model)


def get_embedder() -> Embedder:
    """The process-wide embedder, loaded on first use."""
    with _lock:  # concurrent first requests must not each load the model
        return _load()
