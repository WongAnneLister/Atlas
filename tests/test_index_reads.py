from unittest.mock import Mock

import pytest
from pymilvus.exceptions import MilvusException

from support_agent.config import Settings
from support_agent.retrieval.milvus_store import MilvusStore


def test_alias_readiness_and_build_id_ttl(monkeypatch) -> None:
    config = Settings()
    client = Mock()
    values = iter([0.0, 1.0, config.index.alias_ttl_s + 1, config.index.alias_ttl_s * 3])
    monkeypatch.setattr("support_agent.retrieval.milvus_store.monotonic", lambda: next(values))
    store = MilvusStore(config, client)
    client.describe_alias.return_value = {"collection_name": config.index.collection_prefix + "aa"}
    assert store.current_build_id() == "aa"
    client.describe_alias.return_value = {"collection_name": config.index.collection_prefix + "bb"}
    assert store.current_build_id() == "aa"
    assert store.current_build_id() == "bb"
    client.describe_alias.side_effect = MilvusException(message="alias not found")
    assert store.current_build_id() is None
    assert not store.ready()
    client.has_collection.assert_not_called()


def test_last_build_file_refuses_to_hydrate_another_build(tmp_path) -> None:
    from support_agent.retrieval.index_snapshot import load_latest_chunks

    config = Settings()
    config.data.processed_dir = str(tmp_path)
    (tmp_path / "chunks.jsonl").write_text("")
    (tmp_path / "ingest_run.json").write_text('{"build_id":"aa","chunk_hash":"irrelevant"}')
    with pytest.raises(ValueError, match="build id"):
        load_latest_chunks(config, expected_build_id="bb")
