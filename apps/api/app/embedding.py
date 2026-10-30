from collections import OrderedDict
from functools import cache
from threading import Lock
from typing import Protocol

from worker.embed import load_model

from app.config import settings


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...


# Query embeddings kept, most recently used, so a repeated question is not embedded again.
QUERY_CACHE = 512


class LocalEmbedder:
    def __init__(self, model_name: str) -> None:
        # The same copy the ingest pipeline uses, so the model is in memory once.
        self.model = load_model(model_name)
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_lock = Lock()

    def embed(self, text: str) -> list[float]:
        with self._cache_lock:
            if text in self._cache:
                self._cache.move_to_end(text)
                return self._cache[text]
        vector = self.model.encode([text])[0].tolist()
        with self._cache_lock:
            self._cache[text] = vector
            if len(self._cache) > QUERY_CACHE:
                self._cache.popitem(last=False)
        return vector


_lock = Lock()


@cache
def _load() -> Embedder:
    return LocalEmbedder(settings.embedding_model)


def get_embedder() -> Embedder:
    """The process-wide embedder, loaded on first use."""
    with _lock:  # concurrent first requests must not each load the model
        return _load()
