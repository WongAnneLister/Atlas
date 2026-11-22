"""Pinned BGE cross-encoder scores and a capped retrieval wrapper."""

from __future__ import annotations

import logging
import math
from contextlib import AbstractContextManager
from typing import Any, Protocol

from support_agent.config import REPO_ROOT, RetrievalSettings, get_settings
from support_agent.retrieval.filters import RetrievalFilters, filter_scope, supports_filters
from support_agent.retrieval.types import RetrievedChunk, Retriever


class Reranker(Protocol):
    def rerank(self, query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]: ...


def rank_by_logits(chunks: list[RetrievedChunk], logits: list[float]) -> list[RetrievedChunk]:
    if len(chunks) != len(logits) or not all(math.isfinite(value) for value in logits):
        raise ValueError("Reranker must return one finite logit per chunk")
    output: list[RetrievedChunk] = []
    for chunk, logit in zip(chunks, logits, strict=True):
        exp = math.exp(-abs(logit))
        sigmoid = 1 / (1 + exp) if logit >= 0 else exp / (1 + exp)
        output.append(
            chunk.model_copy(
                update={
                    "scores": {**chunk.scores, "rerank_logit": logit, "rerank": sigmoid},
                    "ranks": dict(chunk.ranks),
                }
            )
        )
    output.sort(key=lambda chunk: (-chunk.scores["rerank_logit"], chunk.chunk_id))
    for rank, chunk in enumerate(output, start=1):
        chunk.ranks["rerank"] = rank
    return output


def cache_reranker(config: RetrievalSettings) -> str:
    from huggingface_hub import snapshot_download

    return str(
        snapshot_download(
            config.reranker_model,
            revision=config.reranker_revision,
            cache_dir=str(REPO_ROOT / config.reranker_cache_dir),
            allow_patterns=["*.json", "model.safetensors", "sentencepiece.bpe.model"],
        )
    )


class BgeReranker:
    def __init__(self, config: RetrievalSettings, backend: Any = None) -> None:
        self.config = config
        if backend is None:
            import torch
            from FlagEmbedding import FlagReranker

            torch.set_num_threads(config.reranker_cpu_threads)
            backend = FlagReranker(
                cache_reranker(config),
                devices=config.reranker_device,
                use_fp16=config.reranker_use_fp16,
            )
        self.backend = backend

    def rerank(self, query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        if not chunks:
            return []
        return rank_by_logits(chunks, self.logits(query, [chunk.text for chunk in chunks]))

    def logits(self, query: str, texts: list[str]) -> list[float]:
        """Raw cross-encoder logits for (query, text) pairs, in input order."""
        values = self.backend.compute_score(
            [(query, text) for text in texts],
            batch_size=self.config.reranker_batch_size,
            max_length=self.config.reranker_max_tokens,
            normalize=False,
        )
        values = values.tolist() if hasattr(values, "tolist") else values
        return [float(values)] if isinstance(values, (int, float)) else list(map(float, values))


class FakeReranker:
    def __init__(self, logits: dict[str, float] | None = None) -> None:
        self.logits = logits or {}

    def rerank(self, query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        return rank_by_logits(chunks, [self.logits.get(chunk.chunk_id, 0.0) for chunk in chunks])


class RerankingRetriever:
    def __init__(
        self,
        base: Retriever,
        reranker: Reranker,
        candidates_k: int,
        top_k: int,
        dedupe_text: bool = False,
    ) -> None:
        if not 0 < top_k <= candidates_k:
            raise ValueError("Need a positive top_k no larger than candidates_k")
        self.base, self.reranker = base, reranker
        self.candidates_k, self.top_k = candidates_k, top_k
        self.dedupe_text = dedupe_text

    def supports_filters(self) -> bool:
        return supports_filters(self.base)

    def filter_scope(self) -> AbstractContextManager[None]:
        return filter_scope(self.base)

    def retrieve(
        self, query: str, top_k: int | None = None, filters: RetrievalFilters | None = None
    ) -> list[RetrievedChunk]:
        limit = self.top_k if top_k is None else min(top_k, self.top_k)
        if limit <= 0:
            raise ValueError("top_k must be positive")
        candidates = (
            self.base.retrieve(query, self.candidates_k)
            if filters is None
            else self.base.retrieve(query, self.candidates_k, filters=filters)
        )
        ranked = self.reranker.rerank(query, candidates)
        return (unique_text(ranked) if self.dedupe_text else ranked)[:limit]


def unique_text(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Keep the first chunk of each distinct text (whitespace-insensitive), in rank order."""
    seen: set[str] = set()
    kept: list[RetrievedChunk] = []
    for chunk in chunks:
        key = " ".join(chunk.text.split())
        if key not in seen:
            seen.add(key)
            kept.append(chunk)
    return kept


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger(__name__).info("Reranker cache: %s", cache_reranker(get_settings().retrieval))
