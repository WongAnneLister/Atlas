"""BGE-M3 dense encoding with bounded windows, and deterministic offline test vectors."""

from __future__ import annotations

import hashlib
import logging
import math
from threading import Lock
from typing import Any, Protocol

from support_agent.config import REPO_ROOT, RetrievalSettings, get_settings
from support_agent.retrieval.chunking import split_text
from support_agent.retrieval.tokenization import BgeTokenizer, Tokenizer


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def normalise(vector: list[float]) -> list[float]:
    if not vector or not all(math.isfinite(value) for value in vector):
        raise ValueError("Embedding vector is empty or nonfinite")
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        raise ValueError("Embedding vector has zero norm")
    return [value / norm for value in vector]


class FakeEmbedder:
    def __init__(self, dimension: int) -> None:
        if dimension <= 0:
            raise ValueError("Embedding dimension must be positive")
        self.dimension = dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [
            normalise(
                [
                    int.from_bytes(hashlib.sha256(f"{text}:{index}".encode()).digest(), "big")
                    / (1 << (hashlib.sha256().digest_size * 8))
                    - 0.5
                    for index in range(self.dimension)
                ]
            )
            for text in texts
        ]


def cache_model(settings: RetrievalSettings) -> str:
    from huggingface_hub import snapshot_download

    logging.getLogger("httpx").setLevel(logging.WARNING)
    return str(
        snapshot_download(
            settings.embedding_model,
            revision=settings.embedding_revision,
            cache_dir=str(REPO_ROOT / settings.embedding_cache_dir),
            headers={"Accept-Encoding": "identity"},
            allow_patterns=[
                "*.json",
                "pytorch_model.bin",
                "sentencepiece.bpe.model",
                "*_linear.pt",
            ],
        )
    )


class BgeM3Embedder:
    def __init__(
        self,
        settings: RetrievalSettings,
        tokenizer: Tokenizer | None = None,
        backend: Any = None,
    ) -> None:
        self.settings = settings
        self.tokenizer = tokenizer or BgeTokenizer(settings)
        if backend is None:
            import torch
            from FlagEmbedding import BGEM3FlagModel

            torch.set_num_threads(settings.embedding_cpu_threads)
            snapshot = cache_model(settings)
            backend = BGEM3FlagModel(
                snapshot,
                devices=settings.embedding_device,
                use_fp16=settings.embedding_use_fp16,
                normalize_embeddings=settings.embedding_normalize,
            )
        self.backend = backend
        self.window_count = 0
        self._encode_lock = Lock()

    def embed(self, texts: list[str]) -> list[list[float]]:
        # Parallel query parts share the backend and its worker state.
        with self._encode_lock:
            return self._embed(texts)

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # Reserve the encoder's leading/trailing special tokens within the configured total budget.
        special_tokens = 2
        budget = (
            min(self.settings.embedding_window_tokens, self.settings.embedding_max_tokens)
            - special_tokens
        )
        windows: list[str] = []
        owners: list[tuple[int, int]] = []
        for owner, text in enumerate(texts):
            pieces = split_text(text, self.tokenizer, budget, overlap=0)
            if not pieces:
                raise ValueError("Cannot embed empty text")
            for piece in pieces:
                windows.append(piece)
                owners.append((owner, self.tokenizer.count(piece)))
        sums = [[0.0] * self.settings.embedding_dim for _ in texts]
        weights = [0] * len(texts)
        batch_size = self.settings.embedding_batch_size
        for offset in range(0, len(windows), batch_size):
            batch = windows[offset : offset + batch_size]
            output = self.backend.encode(
                batch,
                batch_size=batch_size,
                max_length=self.settings.embedding_window_tokens,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )["dense_vecs"]
            vectors = output.tolist() if hasattr(output, "tolist") else output
            if len(vectors) != len(batch):
                raise ValueError("BGE returned the wrong number of vectors")
            for position, values in enumerate(vectors):
                vector = [float(value) for value in values]
                if len(vector) != self.settings.embedding_dim:
                    raise ValueError("BGE returned the wrong vector dimension")
                if not all(math.isfinite(value) for value in vector):
                    raise ValueError("BGE returned nonfinite vector values")
                vector = normalise(vector) if self.settings.embedding_normalize else vector
                owner, weight = owners[offset + position]
                for axis, value in enumerate(vector):
                    sums[owner][axis] += value * weight
                weights[owner] += weight
        self.window_count += len(windows)
        averaged = [
            [value / weights[index] for value in vector] for index, vector in enumerate(sums)
        ]
        return (
            [normalise(vector) for vector in averaged]
            if self.settings.embedding_normalize
            else averaged
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger(__name__).info("Embedding cache: %s", cache_model(get_settings().retrieval))
