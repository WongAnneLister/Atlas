"""Shared retrieval results and the query interface, independent of Milvus."""

from typing import Protocol

from pydantic import Field

from support_agent.retrieval.chunking import Chunk


class RetrievedChunk(Chunk):
    scores: dict[str, float] = Field(default_factory=dict)
    ranks: dict[str, int] = Field(default_factory=dict)


class Retriever(Protocol):
    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]: ...
