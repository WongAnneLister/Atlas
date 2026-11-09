from __future__ import annotations

import pytest

from support_agent.config import get_settings
from support_agent.ingest import ingest_chunks
from support_agent.retrieval.chunking import Chunk
from support_agent.retrieval.embed import FakeEmbedder
from support_agent.retrieval.milvus_store import DESCRIPTION, MilvusStore


def chunk() -> Chunk:
    return Chunk(
        chunk_id="fixture",
        doc_id="returns",
        section_id="returns.window",
        title="Returns",
        heading_path="Returns > Window",
        text="Return within 30 days.",
        n_tokens=5,
    )


class Client:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []
        self.collection_args: dict[str, object] = {}
        self.description = DESCRIPTION
        self.exists = False
        self.drops = 0

    def has_collection(self, **kwargs: object) -> bool:
        return self.exists

    def describe_collection(self, **kwargs: object) -> dict[str, object]:
        return {"description": self.description}

    def drop_collection(self, **kwargs: object) -> None:
        self.drops += 1
        self.rows.clear()

    def create_collection(self, **kwargs: object) -> None:
        self.exists = True
        self.collection_args = kwargs

    def upsert(
        self, collection_name: str, data: list[dict[str, object]], **kwargs: object
    ) -> dict[str, int]:
        self.rows.extend(data)
        return {"upsert_count": len(data)}

    def flush(self, **kwargs: object) -> None:
        pass

    def load_collection(self, **kwargs: object) -> None:
        pass

    def query(self, **kwargs: object) -> list[dict[str, int]]:
        return [{"count(*)": len(self.rows)}]


def test_dense_and_bm25_schema_and_upsert_omit_generated_sparse_values() -> None:
    settings = get_settings()
    client = Client()
    store = MilvusStore(settings, client)
    assert (
        ingest_chunks([chunk()], FakeEmbedder(settings.retrieval.embedding_dim), store, settings)
        == 1
    )
    schema = client.collection_args["schema"].to_dict()
    fields = {field["name"]: field for field in schema["fields"]}
    assert fields["text"]["params"]["enable_analyzer"] is True
    assert fields["dense"]["params"]["dim"] == settings.retrieval.embedding_dim
    assert schema["functions"][0]["input_field_names"] == ["text"]
    assert schema["functions"][0]["output_field_names"] == ["sparse"]
    assert "sparse" not in client.rows[0]
    assert client.rows[0]["text"] == chunk().text
    store.create_or_reset()
    assert client.drops == 1 and not client.rows


def test_store_refuses_foreign_collection_reset() -> None:
    client = Client()
    client.exists, client.description = True, "another application's collection"
    with pytest.raises(ValueError, match="Refusing to reset"):
        MilvusStore(get_settings(), client).create_or_reset()
    assert client.drops == 0


@pytest.mark.parametrize("bad", ["shape", "nonfinite", "bytes"])
def test_invalid_rows_fail_before_reset(bad: str) -> None:
    settings = get_settings()
    client = Client()
    client.exists = True
    store = MilvusStore(settings, client)
    item = chunk()
    vector = FakeEmbedder(settings.retrieval.embedding_dim).embed([item.text])[0]
    if bad == "shape":
        vector = vector[:-1]
    elif bad == "nonfinite":
        vector[0] = float("nan")
    else:
        item.text = "界" * settings.milvus.text_max_bytes
    with pytest.raises(ValueError):
        store.validate([item], [vector])
    assert client.drops == 0 and not client.rows


def test_zero_search_limit_is_rejected() -> None:
    store = MilvusStore(get_settings(), Client())
    with pytest.raises(ValueError, match="positive"):
        store.search_bm25("returns", limit=0)


def test_bad_embedding_keeps_the_previous_collection() -> None:
    settings = get_settings()
    client = Client()
    client.exists = True

    class BadEmbedder:
        def embed(self, texts: list[str]) -> list[list[float]]:
            return [[1.0]]

    with pytest.raises(ValueError, match="Invalid dense vector"):
        ingest_chunks([chunk()], BadEmbedder(), MilvusStore(settings, client), settings)
    assert client.drops == 0 and client.exists
