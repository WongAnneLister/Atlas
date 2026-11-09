"""Cached component measurements, reused without treating cache lookups as model latency."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

from eval.retrieval_records import SearchRecord
from eval.schema import EvalItem
from support_agent.config import Settings
from support_agent.data.doc_models import digest, json_text, write_text
from support_agent.retrieval.bm25 import Bm25Retriever
from support_agent.retrieval.dense import DenseRetriever
from support_agent.retrieval.embed import Embedder
from support_agent.retrieval.hybrid import HybridRetriever
from support_agent.retrieval.milvus_store import SearchStore
from support_agent.retrieval.rerank import Reranker, RerankingRetriever
from support_agent.retrieval.types import RetrievedChunk


class FrozenRetriever:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self.chunks = chunks

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        return self.chunks[:top_k]


class Experiment:
    def __init__(
        self,
        settings: Settings,
        store: SearchStore,
        embedder: Embedder,
        reranker: Reranker,
        cache_dir: Path,
        snapshot: str,
        *,
        dense_source: Experiment | None = None,
        bm25_source: Experiment | None = None,
    ) -> None:
        self.settings, self.store = settings, store
        self.embedder, self.reranker = embedder, reranker
        self.cache_dir = cache_dir
        self.component_sources = {"dense": dense_source, "bm25": bm25_source}
        self.provenance = digest(snapshot + json_text(settings.model_dump(mode="json")))

    def retrieve(self, mode: str, item: EvalItem) -> SearchRecord:
        source = self.component_sources.get(mode)
        if source is not None:
            return source.retrieve(mode, item)
        key = digest(json_text([mode, self.provenance, item.question]))
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            cached = SearchRecord.model_validate_json(path.read_text(encoding="utf-8"))
            if cached.provenance != self.provenance or cached.item != item or cached.mode != mode:
                raise ValueError("Retrieval cache provenance mismatch")
            return cached.model_copy(update={"cache_hit": True})
        config = self.settings.retrieval
        if mode in ("dense", "bm25"):
            retriever = (
                DenseRetriever(self.store, self.embedder)
                if mode == "dense"
                else Bm25Retriever(self.store, config)
            )
            depth = config.dense_top_k if mode == "dense" else config.bm25_top_k
            started = perf_counter()
            chunks = retriever.retrieve(item.question, depth)
            components = {mode: perf_counter() - started}
        elif mode == "hybrid":
            dense, lexical = self.retrieve("dense", item), self.retrieve("bm25", item)
            started = perf_counter()
            chunks = HybridRetriever(
                FrozenRetriever(dense.chunks), FrozenRetriever(lexical.chunks), config
            ).retrieve(item.question, config.rerank_candidates_k)
            components = {
                **dense.components_s,
                **lexical.components_s,
                "fusion": perf_counter() - started,
            }
        elif mode == "hybrid_rerank":
            base = self.retrieve("hybrid", item)
            started = perf_counter()
            chunks = RerankingRetriever(
                FrozenRetriever(base.chunks),
                self.reranker,
                config.rerank_candidates_k,
                config.rerank_top_k,
            ).retrieve(item.question, config.rerank_top_k)
            components = {**base.components_s, "rerank": perf_counter() - started}
        else:
            raise ValueError(f"Unknown retrieval mode: {mode}")
        record = SearchRecord(
            item=item,
            mode=mode,
            chunks=chunks,
            latency_s=sum(components.values()),
            components_s=components,
            provenance=self.provenance,
        )
        write_text(path, record.model_dump_json() + "\n")
        return record
