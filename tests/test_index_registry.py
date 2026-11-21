from alembic import command
from sqlalchemy import URL, inspect

from support_agent.config import Settings
from support_agent.db.engine import make_engine
from support_agent.db.migrate import alembic_config, upgrade


def test_index_registry_migrates_and_can_downgrade_on_scratch_sqlite(tmp_path) -> None:
    from support_agent.retrieval.index_tables import metadata

    settings = Settings()
    engine = make_engine(
        URL.create("sqlite", database=str(tmp_path / "scratch.sqlite")), settings.db
    )
    try:
        upgrade(engine)
        assert set(metadata.tables) <= set(inspect(engine).get_table_names())
        with engine.begin() as connection:
            command.downgrade(alembic_config(connection), "0002_refund_idempotency")
            assert not (set(metadata.tables) & set(inspect(connection).get_table_names()))
        upgrade(engine)
        assert set(metadata.tables) <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_alias_registry_compare_and_set(tmp_path) -> None:
    import pytest

    from support_agent.retrieval.index_models import BuildRecord
    from support_agent.retrieval.registry import IndexRegistry

    conn = URL.create("sqlite", database=str(tmp_path / "registry.sqlite"))
    registry = IndexRegistry(make_engine(conn, Settings().db))
    try:
        registry.initialize()
        registry.begin_build(
            BuildRecord(
                build_id="aa",
                collection="fixture_aa",
                mode="full",
                fingerprint="fixture",
                embed_model="fake",
                embed_revision="fake",
                chunker_version="test",
                docs_hash="corpus",
                status="built",
            )
        )
        with registry.locked_alias("fixture_live") as lock:
            lock.swap(None, "aa")
            with pytest.raises(RuntimeError, match="alias changed"):
                lock.swap(None, "aa")
        assert registry.get_alias("fixture_live").build_id == "aa"
        assert registry.get_build("aa").status == "released"
    finally:
        registry.close()
