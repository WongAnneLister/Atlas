"""Retrieve both candidate lists and retain their ranks alongside the RRF score."""

from collections.abc import Iterator
from contextlib import contextmanager

from support_agent.config import RetrievalSettings
from support_agent.retrieval.filters import RetrievalFilters, filter_scope, supports_filters
from support_agent.retrieval.fusion import rrf
from support_agent.retrieval.types import RetrievedChunk, Retriever


class HybridRetriever:
    def __init__(self, dense: Retriever, bm25: Retriever, config: RetrievalSettings) -> None:
        self.dense = dense
        self.bm25 = bm25
        self.config = config

    def supports_filters(self) -> bool:
        dense = supports_filters(self.dense)
        bm25 = supports_filters(self.bm25)
        if dense != bm25:
            raise TypeError("Hybrid retrieval sources disagree on filter support")
        return dense

    @contextmanager
    def filter_scope(self) -> Iterator[None]:
        with filter_scope(self.dense), filter_scope(self.bm25):
            yield

    def retrieve(
        self, query: str, top_k: int, filters: RetrievalFilters | None = None
    ) -> list[RetrievedChunk]:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        kwargs = {"filters": filters} if filters is not None else {}
        sources = {
            "dense": self.dense.retrieve(query, self.config.dense_top_k, **kwargs),
            "bm25": self.bm25.retrieve(query, self.config.bm25_top_k, **kwargs),
        }
        chunks: dict[str, RetrievedChunk] = {}
        for source, results in sources.items():
            for rank, result in enumerate(results, start=1):
                if result.chunk_id not in chunks:
                    chunks[result.chunk_id] = result.model_copy(update={"scores": {}, "ranks": {}})
                chunk = chunks[result.chunk_id]
                chunk.ranks[source] = rank
                if source in result.scores:
                    chunk.scores[source] = result.scores[source]
        fused = rrf(
            {source: [chunk.chunk_id for chunk in results] for source, results in sources.items()},
            self.config.rrf_k,
        )
        output: list[RetrievedChunk] = []
        for chunk_id, score in fused[:top_k]:
            chunk = chunks[chunk_id]
            chunk.scores["rrf"] = score
            output.append(chunk)
        return output
