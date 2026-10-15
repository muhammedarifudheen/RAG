from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from functools import cache
from threading import Lock
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import numpy as np

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


class OnnxModel:
    """A sentence-transformers model run with ONNX Runtime instead of PyTorch.

    Uses the ONNX export published in the model's own repository and reproduces
    sentence-transformers' encode(): the model's word-piece limit, mean pooling over
    real tokens, then unit length. PyTorch and sentence-transformers take about
    420 MB before a model is loaded; this takes a fraction of that, which is what
    lets the server run in a free host's 512 MB.
    """

    def __init__(self, model_name: str) -> None:
        # Imported here: loading the runtime takes a moment and most callers never embed.
        import onnxruntime
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        def fetch(filename: str) -> str:
            return hf_hub_download(model_name, filename)

        with open(fetch("sentence_bert_config.json"), encoding="utf-8") as config:
            max_tokens = int(json.load(config)["max_seq_length"])
        self.tokenizer = Tokenizer.from_file(fetch("tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=max_tokens)
        self.tokenizer.enable_padding()

        options = onnxruntime.SessionOptions()
        options.inter_op_num_threads = 1
        # Memory patterns are planned per input shape, and batches of text vary in
        # length, so they only add memory. Without them the peak is set by the batch
        # size: about 18 MB per text at the full 256 word pieces.
        options.enable_mem_pattern = False
        self.session = onnxruntime.InferenceSession(
            fetch("onnx/model.onnx"), options, providers=["CPUExecutionProvider"]
        )
        self.input_names = {i.name for i in self.session.get_inputs()}

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        """Unit-length embeddings, one row per text."""
        import numpy as np

        encodings = self.tokenizer.encode_batch(list(texts))
        ids = np.array([e.ids for e in encodings], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
        feeds = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self.input_names:
            feeds["token_type_ids"] = np.array([e.type_ids for e in encodings], dtype=np.int64)
        tokens = self.session.run(None, feeds)[0]  # (texts, tokens, dimensions)

        weights = mask[:, :, None].astype(tokens.dtype)
        pooled = (tokens * weights).sum(axis=1) / np.clip(weights.sum(axis=1), 1e-9, None)
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        return pooled / np.clip(norms, 1e-12, None)


_model_lock = Lock()


@cache
def _load_model(model_name: str) -> OnnxModel:
    return OnnxModel(model_name)


def load_model(model_name: str) -> OnnxModel:
    """The process-wide copy of a model, loaded on first use.

    Shared so that a process that both answers questions and ingests (the API)
    holds the model in memory once, not once per ingest.
    """
    with _model_lock:  # concurrent first users must not each load it
        return _load_model(model_name)


class LocalEmbedder:
    def __init__(self, model_name: str, batch_size: int = 16) -> None:
        self.model = load_model(model_name)
        self.batch_size = batch_size

    def encode(
        self, texts: Sequence[str], on_progress: Callable[[int, int], None] | None = None
    ) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            vectors.extend(self.model.encode(texts[start : start + self.batch_size]).tolist())
            if on_progress is not None:
                on_progress(len(vectors), len(texts))
        return vectors
