"""Build configured retrievers; callers may inject and own a shared store."""

from typing import Literal

from support_agent.config import Settings, get_settings
from support_agent.retrieval.bm25 import Bm25Retriever
from support_agent.retrieval.dense import DenseRetriever
from support_agent.retrieval.embed import BgeM3Embedder, Embedder
from support_agent.retrieval.hybrid import HybridRetriever
from support_agent.retrieval.milvus_store import MilvusStore, SearchStore
from support_agent.retrieval.rerank import BgeReranker, Reranker, RerankingRetriever
from support_agent.retrieval.types import Retriever

RetrievalMode = Literal["dense", "bm25", "hybrid", "hybrid_rerank"]


def build_retriever(
    mode: RetrievalMode,
    *,
    settings: Settings | None = None,
    store: SearchStore | None = None,
    embedder: Embedder | None = None,
    reranker: Reranker | None = None,
) -> Retriever:
    if mode not in ("dense", "bm25", "hybrid", "hybrid_rerank"):
        raise ValueError(f"Unknown retrieval mode: {mode}")
    settings = settings or get_settings()
    store = store if store is not None else MilvusStore(settings)
    if mode == "bm25":
        return Bm25Retriever(store, settings.retrieval)
    dense = DenseRetriever(
        store, embedder if embedder is not None else BgeM3Embedder(settings.retrieval)
    )
    if mode == "dense":
        return dense
    hybrid = HybridRetriever(dense, Bm25Retriever(store, settings.retrieval), settings.retrieval)
    if mode == "hybrid":
        return hybrid
    return RerankingRetriever(
        hybrid,
        reranker if reranker is not None else BgeReranker(settings.retrieval),
        settings.retrieval.rerank_candidates_k,
        settings.retrieval.rerank_top_k,
    )
