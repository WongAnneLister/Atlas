"""Dense retrieval using the configured query embedder and vector store."""

from support_agent.retrieval.embed import Embedder
from support_agent.retrieval.milvus_store import SearchStore
from support_agent.retrieval.types import RetrievedChunk


class DenseRetriever:
    def __init__(self, store: SearchStore, embedder: Embedder) -> None:
        self.store = store
        self.embedder = embedder

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        vectors = self.embedder.embed([query])
        if len(vectors) != 1:
            raise ValueError("Expected one query embedding")
        return [
            RetrievedChunk(
                **hit.model_dump(exclude={"score"}),
                scores={"dense": hit.score},
                ranks={"dense": rank},
            )
            for rank, hit in enumerate(self.store.search_dense(vectors[0], top_k), start=1)
        ]
