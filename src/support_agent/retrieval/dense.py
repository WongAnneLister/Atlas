"""Dense retrieval using the configured query embedder and vector store."""

from contextlib import AbstractContextManager

from support_agent.retrieval.embed import Embedder
from support_agent.retrieval.filters import RetrievalFilters, filter_scope, supports_filters
from support_agent.retrieval.milvus_store import SearchStore
from support_agent.retrieval.types import RetrievedChunk


class DenseRetriever:
    def __init__(self, store: SearchStore, embedder: Embedder) -> None:
        self.store = store
        self.embedder = embedder

    def supports_filters(self) -> bool:
        return supports_filters(self.store)

    def filter_scope(self) -> AbstractContextManager[None]:
        return filter_scope(self.store)

    def retrieve(
        self, query: str, top_k: int, filters: RetrievalFilters | None = None
    ) -> list[RetrievedChunk]:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        vectors = self.embedder.embed([query])
        if len(vectors) != 1:
            raise ValueError("Expected one query embedding")
        hits = (
            self.store.search_dense(vectors[0], top_k)
            if filters is None
            else self.store.search_dense(vectors[0], top_k, filters=filters)
        )
        return [
            RetrievedChunk(
                **hit.model_dump(exclude={"score"}),
                scores={"dense": hit.score},
                ranks={"dense": rank},
            )
            for rank, hit in enumerate(hits, start=1)
        ]
