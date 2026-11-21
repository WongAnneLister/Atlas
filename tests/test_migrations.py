"""Atlas migrations and the write guard."""

import pytest
from sqlalchemy import create_engine


def test_migration_write_guard_refuses_foreign_tables() -> None:
    from support_agent.db.migrate import ensure_atlas_schema

    with create_engine("sqlite://").begin() as connection:
        ensure_atlas_schema(connection)
        connection.exec_driver_sql("CREATE TABLE orders (id TEXT)")
        connection.exec_driver_sql("CREATE TABLE checkpoints (id TEXT)")
        ensure_atlas_schema(connection)
        connection.exec_driver_sql("CREATE TABLE foreign_project (id TEXT)")
        with pytest.raises(ValueError, match="unexpected tables"):
            ensure_atlas_schema(connection)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://atlas:atlas@localhost:5432/atlas",
        "postgresql+psycopg://atlas:atlas@127.0.0.1/atlas",
        "postgresql+psycopg://atlas:atlas@localhost:5433/atlas",
    ],
)
def test_write_target_allows_any_explicit_host_and_port(url: str) -> None:
    # Foreign databases are refused by their tables (ensure_atlas_schema), not by port number:
    # CI and other machines may run Atlas's own Postgres on the default port.
    from sqlalchemy.engine import make_url

    from support_agent.db.migrate import require_write_target

    require_write_target(make_url(url))


def test_write_target_requires_an_explicit_host() -> None:
    from sqlalchemy.engine import make_url

    from support_agent.db.migrate import require_write_target

    with pytest.raises(ValueError, match="explicit"):
        require_write_target(make_url("postgresql+psycopg:///atlas?host=/tmp"))


@pytest.mark.integration
def test_migration_round_trip(postgres_database) -> None:
    from alembic import command
    from pydantic import SecretStr
    from sqlalchemy import inspect

    from support_agent.db.engine import make_engine
    from support_agent.db.migrate import alembic_config, migration_at_head, upgrade
    from support_agent.graph.postgres import postgres_saver
    from support_agent.orders.tables import metadata
    from support_agent.retrieval.index_tables import metadata as index_metadata

    settings, url = postgres_database
    settings.database_url = SecretStr(url.render_as_string(hide_password=False))
    engine = make_engine(url, settings.db)
    try:
        with engine.connect() as connection:
            assert not migration_at_head(connection)
            assert not inspect(connection).get_table_names()
        upgrade(engine)
        with engine.connect() as connection:
            assert migration_at_head(connection)
            inspector = inspect(connection)
            assert set(inspector.get_table_names()) == set(metadata.tables) | set(
                index_metadata.tables
            ) | {"alembic_version"}
            constraints = inspector.get_unique_constraints("refund_requests")
            assert any(
                constraint["name"] == "refund_requests_idempotency_key"
                and constraint["column_names"] == ["idempotency_key"]
                for constraint in constraints
            )
        with engine.begin() as connection:
            command.downgrade(alembic_config(connection), "0001_orders")
            assert not migration_at_head(connection)
            columns = inspect(connection).get_columns("refund_requests")
            assert "idempotency_key" not in {column["name"] for column in columns}
        upgrade(engine)
        with engine.begin() as connection:
            assert migration_at_head(connection)
            columns = inspect(connection).get_columns("refund_requests")
            assert "idempotency_key" in {column["name"] for column in columns}
            command.downgrade(alembic_config(connection), "base")
            assert set(inspect(connection).get_table_names()) == {"alembic_version"}
            assert not migration_at_head(connection)
        upgrade(engine)
        with postgres_saver(settings) as saver:
            saver.setup()
            saver.setup()
        with engine.begin() as connection:
            command.check(alembic_config(connection))
    finally:
        engine.dispose()
