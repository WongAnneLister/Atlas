"""Run and inspect Atlas state migrations explicitly."""

import logging
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import URL, Connection, Engine, inspect

from support_agent.config import REPO_ROOT, get_settings
from support_agent.db.engine import make_engine, postgres_url, transaction
from support_agent.orders.tables import metadata

logger = logging.getLogger(__name__)
CHECKPOINT_TABLES = frozenset(
    {"checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations"}
)


def include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    return not (type_ == "table" and name in CHECKPOINT_TABLES)


def require_write_target(url: URL) -> None:
    if not url.host or any(
        key in url.query for key in ("host", "hostaddr", "port", "dbname", "service")
    ):
        raise ValueError("Set an explicit Atlas PostgreSQL host in DATABASE_URL")
    # Another project's database is refused by its tables (ensure_atlas_schema), not by port.
    logger.info(
        "PostgreSQL target host=%s port=%s database=%s", url.host, url.port or 5432, url.database
    )


def ensure_atlas_schema(connection: Connection) -> None:
    inspector = inspect(connection)
    allowed = metadata.tables.keys() | CHECKPOINT_TABLES | {"alembic_version"}
    if set(inspector.get_table_names()) - allowed:
        raise ValueError("Refusing to write to a database with unexpected tables")
    if connection.dialect.name == "postgresql":
        for schema in inspector.get_schema_names():
            if (
                schema != inspector.default_schema_name
                and schema != "information_schema"
                and not schema.startswith("pg_")
                and inspector.get_table_names(schema=schema)
            ):
                raise ValueError("Refusing to write to a database with unexpected tables")


def alembic_config(connection: Connection | None = None) -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


def migration_at_head(connection: Connection) -> bool:
    expected = set(ScriptDirectory.from_config(alembic_config()).get_heads())
    applied = set(MigrationContext.configure(connection).get_current_heads())
    return bool(expected) and applied == expected


def upgrade(engine: Engine) -> None:
    with transaction(engine) as connection:
        ensure_atlas_schema(connection)
        command.upgrade(alembic_config(connection), "head")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        settings = get_settings()
        url = postgres_url(settings)
        require_write_target(url)
        engine = make_engine(url, settings.db)
        try:
            upgrade(engine)
            from support_agent.graph.postgres import postgres_saver

            with postgres_saver(settings) as saver:
                saver.setup()
        finally:
            engine.dispose()
    except ValueError as error:
        logger.error("Migration refused: %s", error)
        return 1
    except Exception as error:
        logger.error("Migration failed: %s", type(error).__name__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
