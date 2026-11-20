"""Synchronous database engines and transaction ownership."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import URL, Connection, Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.pool import NullPool

from support_agent.config import REPO_ROOT, Settings
from support_agent.db.settings import DatabaseSettings


def postgres_url(settings: Settings) -> URL:
    if settings.database_url is None:
        raise ValueError("Postgres requires DATABASE_URL")
    try:
        url = make_url(settings.database_url.get_secret_value())
    except ArgumentError:
        raise ValueError("DATABASE_URL must be a PostgreSQL URL") from None
    if url.drivername not in {"postgresql", "postgresql+psycopg"} or not url.database:
        raise ValueError("DATABASE_URL must name a PostgreSQL database and use psycopg")
    return url.set(drivername="postgresql+psycopg")


def sqlite_path(settings: Settings) -> Path:
    return REPO_ROOT / settings.orders.db_path


def make_engine(url: URL | str, settings: DatabaseSettings) -> Engine:
    url = make_url(url)
    if url.get_backend_name() == "sqlite":
        engine = create_engine(
            url,
            poolclass=NullPool,
            connect_args={"timeout": settings.connect_timeout_s},
            hide_parameters=True,
        )
        event.listen(engine, "connect", _sqlite_connect)
        event.listen(engine, "begin", _sqlite_begin)
        return engine
    return create_engine(
        url,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_timeout=settings.pool_timeout_s,
        pool_pre_ping=settings.pool_pre_ping,
        connect_args={"connect_timeout": settings.connect_timeout_s},
        hide_parameters=True,
    )


def _sqlite_connect(connection: sqlite3.Connection, _: Any) -> None:
    # Python 3.11 sqlite3 otherwise skips BEGIN for DDL.
    connection.isolation_level = None
    connection.execute("PRAGMA foreign_keys = ON")


def _sqlite_begin(connection: Connection) -> None:
    if connection.get_execution_options().get("sqlite_write"):
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    else:
        connection.exec_driver_sql("BEGIN")


@contextmanager
def transaction(engine: Engine, *, write: bool = False) -> Iterator[Connection]:
    if write and engine.dialect.name == "sqlite":
        with engine.connect() as connection:
            connection = connection.execution_options(sqlite_write=True)
            with connection.begin():
                yield connection
    else:
        with engine.begin() as connection:
            yield connection
