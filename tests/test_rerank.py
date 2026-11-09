from __future__ import annotations

import math

import pytest

from support_agent.config import get_settings
from support_agent.retrieval.factory import build_retriever
from support_agent.retrieval.rerank import BgeReranker, FakeReranker, RerankingRetriever
from test_retrieval import QueryEmbedder, SearchStore, item


def test_reranking_reorders_keeps_scores_and_caps_output_without_mutation() -> None:
    chunks = [item(key) for key in ["a", "b", "c"]]
    chunks[0].scores = {"dense": 0.9, "rrf": 0.01}
    chunks[0].ranks = {"dense": 1}
    before = [chunk.model_dump() for chunk in chunks]
    calls: list[tuple[str, int]] = []

    class Base:
        def retrieve(self, query: str, top_k: int) -> list:
            calls.append((query, top_k))
            return chunks

    retriever = RerankingRetriever(Base(), FakeReranker({"a": 1, "b": -2, "c": 3}), 50, 2)
    result = retriever.retrieve("query", 5)
    assert [chunk.chunk_id for chunk in result] == ["c", "a"]
    assert result[0].scores["rerank_logit"] == 3
    assert result[0].scores["rerank"] == pytest.approx(1 / (1 + math.exp(-3)))
    assert result[1].scores["dense"] == 0.9
    assert result[1].ranks == {"dense": 1, "rerank": 2}
    assert calls == [("query", 50)]
    assert before == [chunk.model_dump() for chunk in chunks]
    assert len(retriever.retrieve("query", 1)) == 1


def test_bge_requests_batched_raw_logits_and_handles_extreme_scores() -> None:
    calls: list[tuple[object, dict]] = []

    class Backend:
        def compute_score(self, pairs: list, **kwargs: object) -> list[float]:
            calls.append((pairs, kwargs))
            return [1000.0, -1000.0]

    config = get_settings().retrieval
    chunks = [item("a"), item("b")]
    result = BgeReranker(config, backend=Backend()).rerank("query", chunks)
    assert result[0].scores["rerank"] == 1
    assert result[1].scores["rerank"] == 0
    assert calls == [
        (
            [("query", chunk.text) for chunk in chunks],
            {
                "batch_size": config.reranker_batch_size,
                "max_length": config.reranker_max_tokens,
                "normalize": False,
            },
        )
    ]
    assert BgeReranker(config, backend=Backend()).rerank("query", []) == []


@pytest.mark.parametrize("logits", [[0.0], [float("nan"), 1.0], [float("inf"), 1.0]])
def test_invalid_reranker_output_fails_closed(logits: list[float]) -> None:
    class Backend:
        def compute_score(self, pairs: object, **kwargs: object) -> list[float]:
            return logits

    with pytest.raises(ValueError):
        BgeReranker(get_settings().retrieval, backend=Backend()).rerank("q", [item("a"), item("b")])


def test_factory_wires_hybrid_rerank_with_injected_models() -> None:
    retriever = build_retriever(
        "hybrid_rerank",
        store=SearchStore(),
        embedder=QueryEmbedder(),
        reranker=FakeReranker({"a": 2}),
    )
    result = retriever.retrieve("W40", 5)
    assert result[0].ranks == {"dense": 1, "bm25": 1, "rerank": 1}
    assert set(result[0].scores) == {"dense", "bm25", "rrf", "rerank", "rerank_logit"}


def test_rerank_limits_and_ties() -> None:
    class Empty:
        def retrieve(self, query: str, top_k: int) -> list:
            return []

    with pytest.raises(ValueError):
        RerankingRetriever(Empty(), FakeReranker(), 1, 2)
    retriever = RerankingRetriever(Empty(), FakeReranker(), 50, 5)
    with pytest.raises(ValueError):
        retriever.retrieve("q", 0)
    assert retriever.retrieve("q", 5) == []
    result = FakeReranker().rerank("q", [item("z"), item("a")])
    assert [chunk.chunk_id for chunk in result] == ["a", "z"]
