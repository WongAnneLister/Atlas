from pathlib import Path

import pytest
from eval.retrieval_index import prepare_experiment_index, prepare_heading_ablation

from support_agent.config import get_settings
from test_milvus_store import chunk


def test_heading_ablation_reembeds_body_only_and_reuses_verified_index(tmp_path: Path) -> None:
    settings = get_settings()
    inputs: list[str] = []

    class Embedder:
        def embed(self, texts: list[str]) -> list[list[float]]:
            inputs.extend(texts)
            return [[1.0] for _ in texts]

    class Store:
        def __init__(self) -> None:
            self.collection = settings.retrieval_eval.heading_ablation_collection
            self.resets = 0
            self.chunks = []

        def exists(self) -> bool:
            return bool(self.chunks)

        def create_or_reset(self) -> None:
            self.resets += 1

        def upsert(self, chunks: list, vectors: list) -> None:
            self.chunks = chunks

        def read_chunks(self) -> list:
            return self.chunks

        def collection_identity(self) -> str:
            return "identity"

        def server_version(self) -> str:
            return "fixture"

    store = Store()
    assert prepare_heading_ablation(settings, [chunk()], Embedder(), store, tmp_path) == "identity"
    assert inputs == [chunk().text]
    prepare_heading_ablation(settings, [chunk()], Embedder(), store, tmp_path)
    assert store.resets == 1
    assert inputs == [chunk().text]
    store.collection = settings.milvus.collection
    with pytest.raises(ValueError, match="baseline"):
        prepare_heading_ablation(settings, [chunk()], Embedder(), store, tmp_path)


def test_verified_heading_on_baseline_reuses_vectors_after_database_failure(tmp_path: Path) -> None:
    settings = get_settings()
    inputs: list[str] = []
    items = [chunk().model_copy(update={"chunk_id": "z", "text": "Z"}), chunk()]

    class Embedder:
        def embed(self, texts: list[str]) -> list[list[float]]:
            inputs.extend(texts)
            return [[2.0 if text.endswith("Z") else 1.0] for text in texts]

    class Store:
        collection = settings.retrieval_eval.baseline_collection
        fail = True

        def exists(self) -> bool:
            return False

        def server_version(self) -> str:
            return "fixture"

        def create_or_reset(self) -> None:
            pass

        def upsert(self, chunks: list, vectors: list) -> None:
            if self.fail:
                self.fail = False
                raise RuntimeError("database timeout")
            assert {
                item.chunk_id: vector for item, vector in zip(chunks, vectors, strict=True)
            } == {"fixture": [1.0], "z": [2.0]}

        def read_chunks(self) -> list:
            return items

        def collection_identity(self) -> str:
            return "new-baseline"

    store = Store()
    with pytest.raises(RuntimeError, match="database timeout"):
        prepare_experiment_index(settings, items, Embedder(), store, tmp_path, True)
    assert (
        prepare_experiment_index(settings, list(reversed(items)), Embedder(), store, tmp_path, True)
        == "new-baseline"
    )
    assert len(inputs) == len(items)
