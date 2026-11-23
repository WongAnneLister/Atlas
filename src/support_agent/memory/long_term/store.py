"""Strictly customer-scoped repository for governed long-term memories."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Connection, Engine, create_engine, select, update
from sqlalchemy.pool import StaticPool

from support_agent.config import REPO_ROOT, Settings
from support_agent.db.engine import make_engine, postgres_url, transaction
from support_agent.memory.long_term.models import CustomerMemory, MemoryStorageStats
from support_agent.memory.long_term.tables import customer_memories, metadata
from support_agent.memory.settings import MemoryKind


class CustomerScopeError(ValueError):
    """Raised when a memory repository call lacks a valid customer scope."""


def require_customer_id(customer_id: Any) -> str:
    """Validate that a non-empty, non-wildcard customer_id was provided."""
    if not isinstance(customer_id, str):
        raise CustomerScopeError("customer_id must be a non-empty string")
    cleaned = customer_id.strip()
    if not cleaned or any(ch in cleaned for ch in ("*", "%", "\x00")):
        raise CustomerScopeError("customer_id must be a non-empty concrete identifier")
    return cleaned


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _row_to_memory(row: sa.RowMapping) -> CustomerMemory:
    created = _as_utc(row["created_at"])
    last_used = _as_utc(row["last_used_at"])
    expires = _as_utc(row["expires_at"])
    assert created is not None and last_used is not None and expires is not None
    return CustomerMemory(
        id=str(row["id"]),
        customer_id=str(row["customer_id"]),
        kind=row["kind"],
        content=str(row["content"]),
        structured=dict(row["structured"] or {}),
        embedding=list(row["embedding"]) if row["embedding"] is not None else None,
        idempotency_key=row["idempotency_key"],
        source_conversation_id=str(row["source_conversation_id"]),
        source_turn=int(row["source_turn"]),
        created_at=created,
        last_used_at=last_used,
        expires_at=expires,
        confidence=float(row["confidence"]),
        superseded_by=row["superseded_by"],
        deleted_at=_as_utc(row["deleted_at"]),
    )


class CustomerMemoryStore:
    """Customer-scoped repository with mandatory scope checks and Postgres RLS binding."""

    def __init__(self, engine: Engine, *, owns_engine: bool = False) -> None:
        self._engine = engine
        self._owns_engine = owns_engine

    @classmethod
    def from_sqlite_path(cls, path: Path | str) -> CustomerMemoryStore:
        if str(path) == ":memory:":
            engine = create_engine(
                "sqlite:///:memory:",
                future=True,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        else:
            resolved = Path(path)
            resolved.parent.mkdir(parents=True, exist_ok=True)
            engine = create_engine(
                f"sqlite:///{resolved}",
                future=True,
                connect_args={"check_same_thread": False},
            )
        metadata.create_all(engine, checkfirst=True)
        return cls(engine, owns_engine=True)

    @classmethod
    def from_settings(cls, settings: Settings) -> CustomerMemoryStore:
        if settings.db.backend == "postgres":
            engine = make_engine(postgres_url(settings), settings.db)
            return cls(engine, owns_engine=True)
        raw = Path(settings.memory.long_term.sqlite_path)
        path = raw if raw.is_absolute() else REPO_ROOT / raw
        return cls.from_sqlite_path(path)

    def close(self) -> None:
        if self._owns_engine:
            self._engine.dispose()

    @contextmanager
    def _scoped_connection(self, customer_id: str) -> Iterator[tuple[Connection, str]]:
        cid = require_customer_id(customer_id)
        with transaction(self._engine) as conn:
            if conn.dialect.name == "postgresql":
                conn.execute(
                    sa.text("SELECT set_config('app.customer_id', :cid, true)"),
                    {"cid": cid},
                )
            yield conn, cid

    def list_active(
        self,
        customer_id: str,
        *,
        now: datetime | None = None,
        limit: int | None = None,
    ) -> list[CustomerMemory]:
        """Return non-deleted, non-superseded, non-expired memories for one customer."""
        ref_now = _as_utc(now) or datetime.now(UTC)
        with self._scoped_connection(customer_id) as (conn, cid):
            stmt = (
                select(customer_memories)
                .where(
                    customer_memories.c.customer_id == cid,
                    customer_memories.c.deleted_at.is_(None),
                    customer_memories.c.superseded_by.is_(None),
                    customer_memories.c.expires_at > ref_now,
                )
                .order_by(
                    customer_memories.c.last_used_at.desc(),
                    customer_memories.c.created_at.desc(),
                    customer_memories.c.id.asc(),
                )
            )
            if limit is not None:
                stmt = stmt.limit(limit)
            rows = conn.execute(stmt).mappings().all()
            return [_row_to_memory(row) for row in rows]

    def get(
        self,
        customer_id: str,
        memory_id: str,
        *,
        include_deleted: bool = False,
    ) -> CustomerMemory | None:
        with self._scoped_connection(customer_id) as (conn, cid):
            stmt = select(customer_memories).where(
                customer_memories.c.customer_id == cid,
                customer_memories.c.id == memory_id,
            )
            if not include_deleted:
                stmt = stmt.where(customer_memories.c.deleted_at.is_(None))
            row = conn.execute(stmt).mappings().first()
            return _row_to_memory(row) if row is not None else None

    def insert(
        self,
        customer_id: str,
        *,
        kind: MemoryKind,
        content: str,
        structured: dict[str, Any],
        source_conversation_id: str,
        source_turn: int,
        expires_at: datetime,
        confidence: float,
        idempotency_key: str | None = None,
        embedding: list[float] | None = None,
        now: datetime | None = None,
        supersede_id: str | None = None,
    ) -> CustomerMemory:
        ref_now = _as_utc(now) or datetime.now(UTC)
        exp = _as_utc(expires_at)
        assert exp is not None
        with self._scoped_connection(customer_id) as (conn, cid):
            if idempotency_key:
                existing = (
                    conn.execute(
                        select(customer_memories).where(
                            customer_memories.c.customer_id == cid,
                            customer_memories.c.idempotency_key == idempotency_key,
                        )
                    )
                    .mappings()
                    .first()
                )
                if existing is not None:
                    return _row_to_memory(existing)

            memory_id = f"mem_{uuid.uuid4().hex[:16]}"
            values = {
                "id": memory_id,
                "customer_id": cid,
                "kind": kind,
                "content": content,
                "structured": structured,
                "embedding": embedding,
                "idempotency_key": idempotency_key,
                "source_conversation_id": source_conversation_id,
                "source_turn": source_turn,
                "created_at": ref_now,
                "last_used_at": ref_now,
                "expires_at": exp,
                "confidence": confidence,
                "superseded_by": None,
                "deleted_at": None,
            }
            conn.execute(customer_memories.insert().values(**values))
            if supersede_id:
                conn.execute(
                    update(customer_memories)
                    .where(
                        customer_memories.c.customer_id == cid,
                        customer_memories.c.id == supersede_id,
                        customer_memories.c.deleted_at.is_(None),
                    )
                    .values(superseded_by=memory_id)
                )
            row = (
                conn.execute(
                    select(customer_memories).where(
                        customer_memories.c.customer_id == cid,
                        customer_memories.c.id == memory_id,
                    )
                )
                .mappings()
                .one()
            )
            return _row_to_memory(row)

    def refresh_last_used(
        self,
        customer_id: str,
        memory_id: str,
        *,
        now: datetime | None = None,
        new_expires_at: datetime | None = None,
    ) -> bool:
        ref_now = _as_utc(now) or datetime.now(UTC)
        updates: dict[str, Any] = {"last_used_at": ref_now}
        if new_expires_at is not None:
            updates["expires_at"] = _as_utc(new_expires_at)
        with self._scoped_connection(customer_id) as (conn, cid):
            result = conn.execute(
                update(customer_memories)
                .where(
                    customer_memories.c.customer_id == cid,
                    customer_memories.c.id == memory_id,
                    customer_memories.c.deleted_at.is_(None),
                    customer_memories.c.superseded_by.is_(None),
                )
                .values(**updates)
            )
            return int(result.rowcount or 0) > 0

    def soft_delete(
        self,
        customer_id: str,
        memory_id: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        ref_now = _as_utc(now) or datetime.now(UTC)
        with self._scoped_connection(customer_id) as (conn, cid):
            result = conn.execute(
                update(customer_memories)
                .where(
                    customer_memories.c.customer_id == cid,
                    customer_memories.c.id == memory_id,
                    customer_memories.c.deleted_at.is_(None),
                )
                .values(deleted_at=ref_now)
            )
            return int(result.rowcount or 0) > 0

    def soft_delete_all(
        self,
        customer_id: str,
        *,
        now: datetime | None = None,
    ) -> int:
        ref_now = _as_utc(now) or datetime.now(UTC)
        with self._scoped_connection(customer_id) as (conn, cid):
            result = conn.execute(
                update(customer_memories)
                .where(
                    customer_memories.c.customer_id == cid,
                    customer_memories.c.deleted_at.is_(None),
                )
                .values(deleted_at=ref_now)
            )
            return int(result.rowcount or 0)

    def storage_stats(
        self,
        customer_id: str,
        *,
        now: datetime | None = None,
    ) -> MemoryStorageStats:
        active = self.list_active(customer_id, now=now)
        total_bytes = sum(
            len(m.content.encode("utf-8"))
            + len(json.dumps(m.structured, sort_keys=True).encode("utf-8"))
            for m in active
        )
        return MemoryStorageStats(active_count=len(active), total_bytes=total_bytes)
