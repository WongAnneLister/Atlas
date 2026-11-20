"""Isolated PostgreSQL databases for migration tests and order parity."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

from sqlalchemy import URL

from support_agent.config import Settings
from support_agent.db.engine import make_engine, postgres_url
from support_agent.db.migrate import ensure_atlas_schema, require_write_target


@contextmanager
def scratch_database(settings: Settings) -> Iterator[URL]:
    base = postgres_url(settings)
    require_write_target(base)
    name = f"atlas_probe_{uuid4().hex}"
    engine = make_engine(base, settings.db)
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            ensure_atlas_schema(connection)
            # The database name is generated locally and consists of lowercase ASCII and digits.
            connection.exec_driver_sql(f"CREATE DATABASE {name}")
            try:
                yield base.set(database=name)
            finally:
                connection.exec_driver_sql(f"DROP DATABASE {name}")
    finally:
        engine.dispose()
