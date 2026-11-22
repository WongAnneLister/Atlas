"""Shared retrieval results and the query interface, independent of Milvus."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from pydantic import Field

from support_agent.retrieval.chunking import Chunk

if TYPE_CHECKING:
    from support_agent.retrieval.filters import RetrievalFilters


class RetrievedChunk(Chunk):
    scores: dict[str, float] = Field(default_factory=dict)
    ranks: dict[str, int] = Field(default_factory=dict)


class Retriever(Protocol):
    def retrieve(
        self, query: str, top_k: int, filters: RetrievalFilters | None = None
    ) -> list[RetrievedChunk]: ...
