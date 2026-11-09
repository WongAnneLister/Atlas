from __future__ import annotations

import pytest

import search
from support_agent.config import get_settings
from test_retrieval import item


def test_search_prints_provenance_and_closes_store(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[object] = []

    class Store:
        def __init__(self, settings: object) -> None:
            pass

        def server_version(self) -> str:
            return "fixture"

        def close(self) -> None:
            calls.append("closed")

    class Retriever:
        def retrieve(self, query: str, top_k: int) -> list[object]:
            calls.append((query, top_k))
            return [item("a").model_copy(update={"ranks": {"dense": 1}, "scores": {"rrf": 0.1}})]

    monkeypatch.setattr(search, "MilvusStore", Store)
    monkeypatch.setattr(search, "build_retriever", lambda *args, **kwargs: Retriever())
    monkeypatch.setenv("Q", "Does W40 have a charger?")
    assert search.main(["--mode", "hybrid"]) == 0
    output = capsys.readouterr().out
    assert "product.a [a]" in output
    assert 'ranks={"dense": 1}' in output
    assert 'scores={"rrf": 0.1}' in output
    assert calls == [("Does W40 have a charger?", get_settings().retrieval.search_top_k), "closed"]


def test_search_dependency_error_returns_failure_and_closes_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[bool] = []

    class UnavailableStore:
        def __init__(self, settings: object) -> None:
            pass

        def server_version(self) -> str:
            raise RuntimeError("unavailable")

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(search, "MilvusStore", UnavailableStore)
    assert search.main(["--query", "W40"]) == 1
    assert closed == [True]


def test_search_rejects_missing_query_and_unimplemented_mode_before_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("Q", raising=False)
    with pytest.raises(SystemExit, match="2"):
        search.main([])
    assert search.main(["--query", "W40", "--mode", "hybrid_rerank"]) == 1
