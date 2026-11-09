from __future__ import annotations

import pytest

from support_agent.config import get_settings
from support_agent.retrieval.bm25 import Bm25Retriever, normalise_model_numbers
from support_agent.retrieval.dense import DenseRetriever
from support_agent.retrieval.factory import build_retriever
from support_agent.retrieval.fusion import rrf
from support_agent.retrieval.hybrid import HybridRetriever
from support_agent.retrieval.milvus_store import SearchHit
from support_agent.retrieval.types import RetrievedChunk


def item(chunk_id: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        doc_id="catalog",
        section_id=f"product.{chunk_id}",
        title="Catalog",
        heading_path=f"Catalog > {chunk_id}",
        text=f"Model {chunk_id} instructions.",
        n_tokens=4,
    )


def test_rrf_single_source_and_missing_items() -> None:
    result = rrf({"dense": ["a", "b"], "bm25": ["b"]}, k=60)
    assert [key for key, _ in result] == ["b", "a"]
    assert dict(result)["a"] == pytest.approx(1 / 61)
    assert dict(result)["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert rrf({"dense": [], "bm25": []}, k=60) == []


def test_rrf_ties_use_best_rank_then_id_independent_of_source_order() -> None:
    lists = {"dense": ["z", "a"], "bm25": ["a", "z"]}
    assert rrf(lists, k=60) == rrf(dict(reversed(list(lists.items()))), k=60)
    assert [key for key, _ in rrf(lists, k=60)] == ["a", "z"]
    # Each score is exactly one; the best single rank wins before alphabetical id.
    assert rrf({"one": ["z", "a"], "two": ["b", "a"]}, k=0)[0][0] == "b"


def test_rrf_k_changes_preference_for_agreement() -> None:
    lists = {"dense": ["a", "x", "b"], "bm25": ["c", "y", "b"]}
    assert rrf(lists, k=0)[0][0] == "a"
    assert rrf(lists, k=60)[0][0] == "b"


def test_rrf_rejects_invalid_k_and_duplicate_ids() -> None:
    with pytest.raises(ValueError, match="nonnegative"):
        rrf({"dense": ["a"]}, k=-1)
    with pytest.raises(ValueError, match="Duplicate"):
        rrf({"dense": ["a", "a"]}, k=60)


class FakeRetriever:
    def __init__(self, source: str, ids: list[str]) -> None:
        self.calls: list[tuple[str, int]] = []
        self.results = [
            item(key).model_copy(update={"scores": {source: float(100 - rank)}})
            for rank, key in enumerate(ids, 1)
        ]

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        self.calls.append((query, top_k))
        return self.results[:top_k]


def test_hybrid_uses_configured_depths_preserves_metadata_and_does_not_mutate() -> None:
    config = get_settings().retrieval.model_copy(update={"dense_top_k": 3, "bm25_top_k": 2})
    dense = FakeRetriever("dense", ["a", "b", "d"])
    bm25 = FakeRetriever("bm25", ["c", "b", "e"])
    before = [chunk.model_dump() for chunk in dense.results + bm25.results]
    results = HybridRetriever(dense, bm25, config).retrieve("W-40 charger?", top_k=2)
    assert [chunk.chunk_id for chunk in results] == ["b", "a"]
    assert results[0].ranks == {"dense": 2, "bm25": 2}
    assert results[0].scores == {"dense": 98, "bm25": 98, "rrf": pytest.approx(2 / 62)}
    assert results[1].ranks == {"dense": 1}
    assert results[0].section_id == "product.b"
    assert dense.calls == [("W-40 charger?", 3)]
    assert bm25.calls == [("W-40 charger?", 2)]
    assert before == [chunk.model_dump() for chunk in dense.results + bm25.results]


def test_hybrid_empty_results_and_dependency_failure() -> None:
    config = get_settings().retrieval
    assert (
        HybridRetriever(FakeRetriever("dense", []), FakeRetriever("bm25", []), config).retrieve(
            "missing", 5
        )
        == []
    )

    class BrokenRetriever:
        def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
            raise RuntimeError("dependency unavailable")

    with pytest.raises(RuntimeError, match="dependency unavailable"):
        HybridRetriever(FakeRetriever("dense", ["a"]), BrokenRetriever(), config).retrieve("x", 5)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Does the W-40 come with a charger?", "does the w40 come with a charger?"),
        ("BHD-340/10 vs BHD177/00", "bhd340/10 vs bhd177/00"),
        ("30-day money-back returns", "30-day money-back returns"),
        ("W40 and w-40", "w40 and w40"),
        ("", ""),
    ],
)
def test_model_normaliser(query: str, expected: str) -> None:
    assert normalise_model_numbers(query) == expected
    assert normalise_model_numbers(expected) == expected


class SearchStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, int]] = []

    def search_dense(self, vector: list[float], limit: int) -> list[SearchHit]:
        self.calls.append(("dense", vector, limit))
        return [SearchHit(**item("a").model_dump(exclude={"scores", "ranks"}), score=0.9)]

    def search_bm25(self, text: str, limit: int) -> list[SearchHit]:
        self.calls.append(("bm25", text, limit))
        return [SearchHit(**item("a").model_dump(exclude={"scores", "ranks"}), score=9.0)]


class QueryEmbedder:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.texts.extend(texts)
        return [[0.5, 0.5]]


def test_dense_keeps_original_query_and_bm25_flag_controls_normalisation() -> None:
    store, embedder = SearchStore(), QueryEmbedder()
    config = get_settings().retrieval
    dense = DenseRetriever(store, embedder)
    bm25 = Bm25Retriever(store, config)
    assert dense.retrieve("W-40 Charger?", 3)[0].scores == {"dense": 0.9}
    assert bm25.retrieve("W-40 Charger?", 4)[0].ranks == {"bm25": 1}
    assert embedder.texts == ["W-40 Charger?"]
    assert store.calls == [("dense", [0.5, 0.5], 3), ("bm25", "w40 charger?", 4)]
    config = config.model_copy(update={"bm25_normalise_model_numbers": False})
    Bm25Retriever(store, config).retrieve("W-40 Charger?", 2)
    assert store.calls[-1] == ("bm25", "W-40 Charger?", 2)


@pytest.mark.parametrize("mode", ["dense", "bm25", "hybrid"])
def test_factory_selects_mode_with_injected_dependencies(mode: str) -> None:
    store, embedder = SearchStore(), QueryEmbedder()
    retriever = build_retriever(mode, store=store, embedder=embedder)
    assert retriever.retrieve("W-40", 2)
    assert [call[0] for call in store.calls] == {
        "dense": ["dense"],
        "bm25": ["bm25"],
        "hybrid": ["dense", "bm25"],
    }[mode]


def test_factory_rejects_unknown_mode_before_initialising_dependencies() -> None:
    with pytest.raises(ValueError, match="mode"):
        build_retriever("invalid")


def test_nonpositive_limits_fail_before_io() -> None:
    store, embedder = SearchStore(), QueryEmbedder()
    config = get_settings().retrieval
    retrievers = [
        DenseRetriever(store, embedder),
        Bm25Retriever(store, config),
        HybridRetriever(FakeRetriever("dense", []), FakeRetriever("bm25", []), config),
    ]
    for retriever in retrievers:
        with pytest.raises(ValueError, match="positive"):
            retriever.retrieve("x", 0)
    assert not store.calls and not embedder.texts
