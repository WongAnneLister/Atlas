"""Transactional queue store for human handoffs with atomic claim and state checks."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Engine, case, create_engine, select, update
from sqlalchemy.pool import StaticPool

from support_agent.config import REPO_ROOT, Settings
from support_agent.db.engine import make_engine, postgres_url, transaction
from support_agent.handoff.models import (
    ALL_RESOLUTION_LABELS,
    HandoffItem,
    HandoffStatus,
    ResolutionLabel,
)
from support_agent.handoff.settings import HandoffPriority
from support_agent.handoff.tables import handoffs, metadata


class HandoffNotFoundError(LookupError):
    """Raised when a handoff item does not exist."""


class HandoffStateError(ValueError):
    """Raised when an invalid state transition or concurrent claim conflict occurs."""


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _row_to_item(row: sa.RowMapping) -> HandoffItem:
    created = _as_utc(row["created_at"])
    assert created is not None
    payload = dict(row["payload"] or {})
    return HandoffItem(
        id=str(row["id"]),
        conversation_id=str(row["conversation_id"]),
        customer_id=str(row["customer_id"]),
        reason=str(row["reason"]),
        priority=row["priority"],
        status=row["status"],
        claimed_by=row["claimed_by"],
        payload=payload,
        created_at=created,
        claimed_at=_as_utc(row["claimed_at"]),
        resolved_at=_as_utc(row["resolved_at"]),
        resolution_label=row["resolution_label"],
        resolution_note=row["resolution_note"],
        idempotency_key=row["idempotency_key"],
        hand_back_to_ai=bool(payload.get("hand_back_to_ai", True)),
    )


class HandoffQueueStore:
    """Repository for human handoffs backed by PostgreSQL or SQLite."""

    def __init__(self, engine: Engine, *, owns_engine: bool = False) -> None:
        self._engine = engine
        self._owns_engine = owns_engine

    @classmethod
    def from_sqlite_path(cls, path: Path | str) -> HandoffQueueStore:
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
    def from_settings(cls, settings: Settings) -> HandoffQueueStore:
        if settings.db.backend == "postgres":
            engine = make_engine(postgres_url(settings), settings.db)
            return cls(engine, owns_engine=True)
        raw = Path(settings.handoff.sqlite_path)
        path = raw if raw.is_absolute() else REPO_ROOT / raw
        return cls.from_sqlite_path(path)

    def close(self) -> None:
        if self._owns_engine:
            self._engine.dispose()

    def enqueue(
        self,
        *,
        conversation_id: str,
        customer_id: str,
        reason: str,
        priority: HandoffPriority,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
        now: datetime | None = None,
    ) -> HandoffItem:
        """Create a new open handoff, or return the existing row on idempotency replay."""
        ref_now = _as_utc(now) or datetime.now(UTC)
        stored_payload = dict(payload)
        stored_payload.setdefault("human_thread", [])
        with transaction(self._engine) as conn:
            if idempotency_key:
                existing = (
                    conn.execute(
                        select(handoffs).where(handoffs.c.idempotency_key == idempotency_key)
                    )
                    .mappings()
                    .first()
                )
                if existing is not None:
                    return _row_to_item(existing)

            handoff_id = f"ho_{uuid.uuid4().hex[:16]}"
            conn.execute(
                handoffs.insert().values(
                    id=handoff_id,
                    conversation_id=conversation_id,
                    customer_id=customer_id,
                    reason=reason,
                    priority=priority,
                    status="open",
                    claimed_by=None,
                    payload=stored_payload,
                    created_at=ref_now,
                    claimed_at=None,
                    resolved_at=None,
                    resolution_label=None,
                    resolution_note=None,
                    idempotency_key=idempotency_key,
                )
            )
            row = conn.execute(select(handoffs).where(handoffs.c.id == handoff_id)).mappings().one()
            return _row_to_item(row)

    def get(self, handoff_id: str) -> HandoffItem | None:
        with transaction(self._engine) as conn:
            row = (
                conn.execute(select(handoffs).where(handoffs.c.id == handoff_id)).mappings().first()
            )
            return _row_to_item(row) if row is not None else None

    def list_items(
        self,
        *,
        status: HandoffStatus | None = None,
        limit: int = 100,
    ) -> list[HandoffItem]:
        priority_rank = case(
            (handoffs.c.priority == "high", 0),
            (handoffs.c.priority == "normal", 1),
            else_=2,
        )
        with transaction(self._engine) as conn:
            stmt = select(handoffs)
            if status is not None:
                stmt = stmt.where(handoffs.c.status == status)
            stmt = stmt.order_by(priority_rank.asc(), handoffs.c.created_at.asc()).limit(limit)
            rows = conn.execute(stmt).mappings().all()
            return [_row_to_item(r) for r in rows]

    def claim(
        self,
        handoff_id: str,
        agent_id: str,
        *,
        now: datetime | None = None,
    ) -> HandoffItem:
        """Atomically transition an open handoff to claimed. Raises HandoffStateError on race."""
        agent = agent_id.strip()
        if not agent:
            raise HandoffStateError("agent_id must be non-empty")
        ref_now = _as_utc(now) or datetime.now(UTC)
        with transaction(self._engine) as conn:
            # Atomic conditional update: only one concurrent caller can match status='open'.
            result = conn.execute(
                update(handoffs)
                .where(handoffs.c.id == handoff_id, handoffs.c.status == "open")
                .values(status="claimed", claimed_by=agent, claimed_at=ref_now)
            )
            if int(result.rowcount or 0) != 1:
                existing = (
                    conn.execute(select(handoffs.c.status).where(handoffs.c.id == handoff_id))
                    .mappings()
                    .first()
                )
                if existing is None:
                    raise HandoffNotFoundError(f"Handoff {handoff_id} not found")
                raise HandoffStateError(f"Cannot claim handoff in status '{existing['status']}'")
            row = conn.execute(select(handoffs).where(handoffs.c.id == handoff_id)).mappings().one()
            return _row_to_item(row)

    def add_message(
        self,
        handoff_id: str,
        *,
        sender: str,
        author: str,
        text: str,
        now: datetime | None = None,
    ) -> HandoffItem:
        """Append a customer follow-up or agent reply to the handoff's human_thread."""
        cleaned = text.strip()
        if not cleaned:
            raise HandoffStateError("Message text must be non-empty")
        ref_now = _as_utc(now) or datetime.now(UTC)
        with transaction(self._engine) as conn:
            row = (
                conn.execute(select(handoffs).where(handoffs.c.id == handoff_id)).mappings().first()
            )
            if row is None:
                raise HandoffNotFoundError(f"Handoff {handoff_id} not found")
            if row["status"] == "resolved":
                raise HandoffStateError("Cannot add messages to a resolved handoff")
            if sender == "agent" and row["status"] != "claimed":
                raise HandoffStateError("Handoff must be claimed before an agent can reply")
            payload = dict(row["payload"] or {})
            thread = list(payload.get("human_thread") or [])
            thread.append(
                {
                    "sender": sender,
                    "author": author,
                    "text": cleaned,
                    "created_at": ref_now.isoformat(),
                }
            )
            payload["human_thread"] = thread
            conn.execute(
                update(handoffs).where(handoffs.c.id == handoff_id).values(payload=payload)
            )
            updated = (
                conn.execute(select(handoffs).where(handoffs.c.id == handoff_id)).mappings().one()
            )
            return _row_to_item(updated)

    def resolve(
        self,
        handoff_id: str,
        *,
        agent_id: str,
        label: ResolutionLabel,
        note: str = "",
        hand_back_to_ai: bool = True,
        now: datetime | None = None,
    ) -> HandoffItem:
        """Transition a claimed handoff to resolved with a mandatory label."""
        if label not in ALL_RESOLUTION_LABELS:
            raise HandoffStateError(f"Unsupported resolution label: {label}")
        ref_now = _as_utc(now) or datetime.now(UTC)
        with transaction(self._engine) as conn:
            row = (
                conn.execute(select(handoffs).where(handoffs.c.id == handoff_id)).mappings().first()
            )
            if row is None:
                raise HandoffNotFoundError(f"Handoff {handoff_id} not found")
            if row["status"] != "claimed":
                raise HandoffStateError(
                    f"Cannot resolve handoff in status '{row['status']}'; claim it first"
                )
            if row["claimed_by"] and agent_id and row["claimed_by"] != agent_id:
                raise HandoffStateError(
                    f"Handoff is claimed by '{row['claimed_by']}', not '{agent_id}'"
                )
            payload = dict(row["payload"] or {})
            payload["hand_back_to_ai"] = hand_back_to_ai
            conn.execute(
                update(handoffs)
                .where(handoffs.c.id == handoff_id, handoffs.c.status == "claimed")
                .values(
                    status="resolved",
                    resolved_at=ref_now,
                    resolution_label=label,
                    resolution_note=note.strip(),
                    payload=payload,
                )
            )
            updated = (
                conn.execute(select(handoffs).where(handoffs.c.id == handoff_id)).mappings().one()
            )
            return _row_to_item(updated)
