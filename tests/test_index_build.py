from unittest.mock import Mock

import pytest
from sqlalchemy import URL

from support_agent.config import Settings
from support_agent.db.engine import make_engine
from support_agent.retrieval.embed import FakeEmbedder
from support_agent.retrieval.milvus_store import MilvusStore
from support_agent.retrieval.registry import IndexRegistry
from support_agent.retrieval.tokenization import WhitespaceTokenizer
from test_index_plan import document


def test_reset_rejects_an_alias_without_writes() -> None:
    settings = Settings()
    settings.milvus.collection = "another_alias"
    client = Mock()
    client.describe_alias.return_value = {"collection_name": "immutable_target"}
    with pytest.raises(ValueError, match="alias"):
        MilvusStore(settings, client).create_or_reset()
    client.drop_collection.assert_not_called()
    client.create_collection.assert_not_called()


def test_shared_collections_are_read_only_to_all_mutations() -> None:
    settings = Settings()
    settings.milvus.collection = settings.index.protected_collections[0]
    client = Mock()
    store = MilvusStore(settings, client)
    for operation in (
        store.create_or_reset,
        store.create,
        store.drop,
        lambda: store.upsert([], []),
    ):
        with pytest.raises(ValueError, match="protected"):
            operation()
    assert not client.mock_calls


def test_incremental_build_and_failed_candidate_cleanup(tmp_path) -> None:
    from support_agent.retrieval.index_build import build_index
    from support_agent.retrieval.milvus_store import VectorChunk

    settings = Settings()
    settings.data.processed_dir = str(tmp_path)
    settings.retrieval.embedding_dim = 4
    target = tmp_path / "returns.md"
    target.write_text(
        document(("a", "First", "Keep."), ("b", "Second", "Before."), ("c", "Third", "Deleted."))
    )
    registry = IndexRegistry(
        make_engine(URL.create("sqlite", database=str(tmp_path / "index.sqlite")), settings.db)
    )
    vectors = {}
    fail = False

    def factory(collection):
        class MemoryStore:
            def create(self):
                assert collection not in vectors
                vectors[collection] = []

            def validate(self, chunks, embeddings):
                assert len(chunks) == len(embeddings)

            def upsert(self, chunks, embeddings):
                if fail:
                    raise RuntimeError("synthetic write failure")
                vectors[collection].extend(
                    VectorChunk(chunk=chunk, dense=dense)
                    for chunk, dense in zip(chunks, embeddings, strict=True)
                )

            def count(self):
                return len(vectors[collection])

            def read_chunks(self):
                return [row.chunk for row in vectors[collection]]

            def read_vectors(self, section_ids):
                return [row for row in vectors[collection] if row.chunk.section_id in section_ids]

            def close(self):
                pass

            def drop(self):
                del vectors[collection]

        return MemoryStore()

    def build():
        return build_index(
            settings,
            registry,
            docs_dir=tmp_path,
            tokenizer=WhitespaceTokenizer(),
            embedder=FakeEmbedder(4),
            make_store=factory,
        )

    original = build()
    with registry.locked_alias(settings.index.live_alias) as lock:
        lock.swap(None, original.build_id)
    target.write_text(document(("a", "First", "Keep."), ("b", "Second", "After.")))
    changed = build()
    assert (changed.mode, changed.embedded_chunks, changed.copied_chunks) == ("incremental", 1, 1)
    before = {row.chunk.section_id: row for row in vectors[original.collection]}
    after = {row.chunk.section_id: row for row in vectors[changed.collection]}
    assert after["a"] == before["a"] and "c" not in after
    assert after["b"].chunk.chunk_id == before["b"].chunk.chunk_id
    assert after["b"].chunk.text == "After."
    fail = True
    with pytest.raises(RuntimeError, match="synthetic"):
        build()
    assert {rec.status for rec in registry.builds()} == {"built", "released", "failed"}
    assert set(vectors) == {original.collection, changed.collection}
    registry.close()
