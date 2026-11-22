"""Milvus full-text retrieval with optional query-only model spelling cleanup."""

import re
from contextlib import AbstractContextManager

from support_agent.config import RetrievalSettings
from support_agent.retrieval.filters import RetrievalFilters, filter_scope, supports_filters
from support_agent.retrieval.milvus_store import SearchStore
from support_agent.retrieval.types import RetrievedChunk


def normalise_model_numbers(query: str) -> str:
    return re.sub(r"\b([a-z]+)-(?=\d)", r"\1", query.casefold())


class Bm25Retriever:
    def __init__(self, store: SearchStore, config: RetrievalSettings) -> None:
        self.store = store
        self.config = config

    def supports_filters(self) -> bool:
        return supports_filters(self.store)

    def filter_scope(self) -> AbstractContextManager[None]:
        return filter_scope(self.store)

    def retrieve(
        self, query: str, top_k: int, filters: RetrievalFilters | None = None
    ) -> list[RetrievedChunk]:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        text = normalise_model_numbers(query) if self.config.bm25_normalise_model_numbers else query
        hits = (
            self.store.search_bm25(text, top_k)
            if filters is None
            else self.store.search_bm25(text, top_k, filters=filters)
        )
        return [
            RetrievedChunk(
                **hit.model_dump(exclude={"score"}),
                scores={"bm25": hit.score},
                ranks={"bm25": rank},
            )
            for rank, hit in enumerate(hits, start=1)
        ]
