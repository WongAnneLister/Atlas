from __future__ import annotations

from datetime import date

import pytest

from support_agent.config import Settings
from support_agent.ingest import ingest_chunks
from support_agent.retrieval.chunking import Chunk
from support_agent.retrieval.embed import FakeEmbedder
from support_agent.retrieval.milvus_metadata import (
    LEGACY_CHUNK_FIELDS,
    METADATA_FIELDS,
    chunk_to_row,
)
from support_agent.retrieval.milvus_store import DESCRIPTION, MilvusStore


def fixture_settings() -> Settings:
    settings = Settings()
    settings.milvus.collection = "unit_fixture_collection"
    return settings


def chunk() -> Chunk:
    return Chunk(
        chunk_id="fixture",
        doc_id="returns",
        section_id="returns.window",
        title="Returns",
        heading_path="Returns > Window",
        text="Return within 30 days.",
        n_tokens=5,
        topic="returns",
        effective_from=date(2026, 9, 1),
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
    settings = fixture_settings()
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
    assert client.rows[0]["effective_from_day"] == 20260901
    assert client.rows[0]["effective_to_day"] == settings.policy_versions.open_end_day
    assert "effective_from" not in client.rows[0]
    assert client.rows[0]["text"] == chunk().text
    store.create_or_reset()
    assert client.drops == 1 and not client.rows


def test_store_refuses_foreign_collection_reset() -> None:
    client = Client()
    client.exists, client.description = True, "another application's collection"
    with pytest.raises(ValueError, match="Refusing to reset"):
        MilvusStore(fixture_settings(), client).create_or_reset()
    assert client.drops == 0


@pytest.mark.parametrize("bad", ["shape", "nonfinite", "bytes"])
def test_invalid_rows_fail_before_reset(bad: str) -> None:
    settings = fixture_settings()
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
    store = MilvusStore(fixture_settings(), Client())
    with pytest.raises(ValueError, match="positive"):
        store.search_bm25("returns", limit=0)


def test_bad_embedding_keeps_the_previous_collection() -> None:
    settings = fixture_settings()
    client = Client()
    client.exists = True

    class BadEmbedder:
        def embed(self, texts: list[str]) -> list[list[float]]:
            return [[1.0]]

    with pytest.raises(ValueError, match="Invalid dense vector"):
        ingest_chunks([chunk()], BadEmbedder(), MilvusStore(settings, client), settings)
    assert client.drops == 0 and client.exists


def test_index_snapshot_returns_complete_chunk_fields_and_collection_identity() -> None:
    class SnapshotClient(Client):
        def describe_collection(self, **kwargs: object) -> dict[str, object]:
            return {
                "description": DESCRIPTION,
                "collection_id": 123,
                "fields": [{"name": field} for field in METADATA_FIELDS],
            }

        def query(self, **kwargs: object) -> list[dict[str, object]]:
            assert kwargs["output_fields"] == ["count(*)"]
            return [{"count(*)": 1}]

        def query_iterator(self, **kwargs: object) -> object:
            assert set(kwargs["output_fields"]) == {*LEGACY_CHUNK_FIELDS, *METADATA_FIELDS}
            assert kwargs["batch_size"] == fixture_settings().milvus.query_batch_size
            return Iterator()

    class Iterator:
        read = False

        def next(self) -> list[dict[str, object]]:
            if self.read:
                return []
            self.read = True
            return [chunk_to_row(chunk(), fixture_settings().policy_versions.open_end_day)]

        def close(self) -> None:
            closed.append(True)

    closed: list[bool] = []
    store = MilvusStore(fixture_settings(), SnapshotClient())
    assert store.read_chunks() == [chunk()]
    assert store.collection_identity() == "123"
    assert closed == [True]


def test_verified_local_chunk_hydration_preserves_fields_and_rejects_unknown_ids() -> None:
    class IdClient(Client):
        chunk_id = "fixture"

        def search(self, **kwargs: object) -> list[list[dict[str, object]]]:
            assert kwargs["output_fields"] == ["chunk_id"]
            return [[{"entity": {"chunk_id": self.chunk_id}, "distance": 0.9}]]

    client = IdClient()
    store = MilvusStore(fixture_settings(), client)
    store.use_chunk_snapshot([chunk()])
    result = store.search_bm25("returns")
    assert result[0].model_dump(exclude={"score"}) == chunk().model_dump()
    assert result[0].score == 0.9
    client.chunk_id = "unknown"
    with pytest.raises(ValueError, match="snapshot"):
        store.search_bm25("returns")


def test_only_configured_experiment_collections_accept_experiment_writes() -> None:
    settings = Settings()
    settings.milvus.collection = settings.retrieval_eval.heading_ablation_collection
    client = Client()
    client.exists = True
    store = MilvusStore(settings, client)
    with pytest.raises(ValueError, match="protected"):
        store.create_or_reset()
    store.allow_experiment_writes()
    store.create_or_reset()
    assert client.drops == 1
    for name in ("support_chunks", "support_chunks_faq_v1", settings.index.live_alias):
        other = Settings()
        other.milvus.collection = name
        with pytest.raises(ValueError, match="experiment"):
            MilvusStore(other, Client()).allow_experiment_writes()


@pytest.mark.parametrize("aliases", [[], ["support_chunks_live"]])
def test_drop_reads_the_alias_list_not_the_response_envelope(aliases: list[str]) -> None:
    client = Client()
    client.exists = True
    # pymilvus 3 wraps the list in a dict that is truthy even when it is empty.
    client.list_aliases = lambda **kwargs: {  # type: ignore[attr-defined]
        "aliases": aliases,
        "collection_name": "unit_fixture_collection",
    }
    store = MilvusStore(fixture_settings(), client)
    if aliases:
        with pytest.raises(ValueError, match="alias"):
            store.drop()
        assert client.drops == 0
    else:
        store.drop()
        assert client.drops == 1


def test_filter_scope_pins_capability_and_both_searches_to_same_physical_schema() -> None:
    from support_agent.retrieval.factory import build_retriever
    from support_agent.retrieval.filters import RetrievalFilters, retrieve_with_filters

    settings = fixture_settings()
    settings.milvus.collection = settings.index.live_alias
    config = settings.policy_versions

    class MovingAlias(Client):
        def __init__(self) -> None:
            super().__init__()
            self.targets = iter(("old", "new"))
            self.searches: list[tuple[str, str, str]] = []

        def describe_alias(self, **kwargs: object) -> dict[str, str]:
            return {"collection_name": next(self.targets)}

        def describe_collection(self, **kwargs: object) -> dict[str, object]:
            has_metadata = kwargs["collection_name"] == "new"
            return {"fields": [{"name": field} for field in METADATA_FIELDS if has_metadata]}

        def search(self, **kwargs: object) -> list[list[dict[str, object]]]:
            target = str(kwargs["collection_name"])
            self.searches.append((target, str(kwargs["anns_field"]), str(kwargs["filter"])))
            row = (
                chunk_to_row(chunk(), config.open_end_day)
                if target == "new"
                else chunk().model_dump(include=set(LEGACY_CHUNK_FIELDS))
            )
            return [[{"entity": row, "distance": 0.9}]]

    client = MovingAlias()
    store = MilvusStore(settings, client)
    retriever = build_retriever(
        "hybrid",
        settings=settings,
        store=store,
        embedder=FakeEmbedder(settings.retrieval.embedding_dim),
    )
    filters = RetrievalFilters(as_of=date(2026, 9, 1), product_category="headphones")
    old, old_applied = retrieve_with_filters(retriever, "returns", 5, filters)
    new, new_applied = retrieve_with_filters(retriever, "returns", 5, filters)
    assert not old_applied and old[0].effective_from is None
    assert new_applied and new[0].effective_from == date(2026, 9, 1)
    assert client.searches == [
        ("old", "dense", ""),
        ("old", "sparse", ""),
        ("new", "dense", filters.to_expr()),
        ("new", "sparse", filters.to_expr()),
    ]
