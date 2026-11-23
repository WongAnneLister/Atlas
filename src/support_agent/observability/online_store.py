"""Repository for online feedback, turn telemetry, and stratified review queue."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, create_engine, select, update
from sqlalchemy.pool import StaticPool

from support_agent.config import REPO_ROOT, Settings
from support_agent.db.engine import make_engine, postgres_url, transaction
from support_agent.guardrails.pii import redact_pii
from support_agent.observability.online_tables import (
    metadata,
    online_turn_events,
    sampled_reviews,
    turn_feedback,
)

FeedbackRating = Literal["up", "down"]
ReviewRubric = Literal["correct", "partially_correct", "wrong", "should_have_handed_off"]
ReviewStatus = Literal["pending", "reviewed"]


class FeedbackRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    message_id: str
    conversation_id: str
    customer_id: str
    trace_id: str | None = None
    rating: FeedbackRating
    reason: str | None = None
    created_at: datetime


class TurnEventRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    conversation_id: str
    customer_id: str
    trace_id: str | None = None
    intent: str | None = None
    path: str | None = None
    gate_score: float | None = None
    gate_passed: bool | None = None
    handoff_reason: str | None = None
    rewrite_skipped: bool = False
    tokens_total: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    citation_valid: bool | None = None
    claims_removed: int = Field(default=0, ge=0)
    guardrail_flags: list[str] = Field(default_factory=list)
    question_redacted: str = ""
    answer_redacted: str = ""
    created_at: datetime


class SampledReviewRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    turn_event_id: str
    conversation_id: str
    intent: str | None = None
    gate_score: float | None = None
    question_text: str
    answer_text: str
    status: ReviewStatus
    rubric_label: ReviewRubric | None = None
    reviewer_id: str | None = None
    note: str | None = None
    created_at: datetime
    reviewed_at: datetime | None = None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _row_to_feedback(row: sa.RowMapping) -> FeedbackRecord:
    created = _as_utc(row["created_at"])
    assert created is not None
    return FeedbackRecord(
        id=str(row["id"]),
        message_id=str(row["message_id"]),
        conversation_id=str(row["conversation_id"]),
        customer_id=str(row["customer_id"]),
        trace_id=row["trace_id"],
        rating=row["rating"],
        reason=row["reason"],
        created_at=created,
    )


def _row_to_event(row: sa.RowMapping) -> TurnEventRecord:
    created = _as_utc(row["created_at"])
    assert created is not None
    return TurnEventRecord(
        id=str(row["id"]),
        conversation_id=str(row["conversation_id"]),
        customer_id=str(row["customer_id"]),
        trace_id=row["trace_id"],
        intent=row["intent"],
        path=row["path"],
        gate_score=float(row["gate_score"]) if row["gate_score"] is not None else None,
        gate_passed=bool(row["gate_passed"]) if row["gate_passed"] is not None else None,
        handoff_reason=row["handoff_reason"],
        rewrite_skipped=bool(row["rewrite_skipped"]),
        tokens_total=int(row["tokens_total"]),
        cost_usd=float(row["cost_usd"]),
        citation_valid=bool(row["citation_valid"]) if row["citation_valid"] is not None else None,
        claims_removed=int(row["claims_removed"]),
        guardrail_flags=list(row["guardrail_flags"] or []),
        question_redacted=str(row["question_redacted"]),
        answer_redacted=str(row["answer_redacted"]),
        created_at=created,
    )


def _row_to_review(row: sa.RowMapping) -> SampledReviewRecord:
    created = _as_utc(row["created_at"])
    assert created is not None
    return SampledReviewRecord(
        id=str(row["id"]),
        turn_event_id=str(row["turn_event_id"]),
        conversation_id=str(row["conversation_id"]),
        intent=row["intent"],
        gate_score=float(row["gate_score"]) if row["gate_score"] is not None else None,
        question_text=str(row["question_text"]),
        answer_text=str(row["answer_text"]),
        status=row["status"],
        rubric_label=row["rubric_label"],
        reviewer_id=row["reviewer_id"],
        note=row["note"],
        created_at=created,
        reviewed_at=_as_utc(row["reviewed_at"]),
    )


class OnlineEvalStore:
    """SQLite/Postgres repository for feedback, turn telemetry, and sampled reviews."""

    def __init__(self, engine: Engine, *, owns_engine: bool = False) -> None:
        self._engine = engine
        self._owns_engine = owns_engine

    @classmethod
    def from_sqlite_path(cls, path: Path | str) -> OnlineEvalStore:
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
    def from_settings(cls, settings: Settings) -> OnlineEvalStore:
        if settings.db.backend == "postgres":
            engine = make_engine(postgres_url(settings), settings.db)
            return cls(engine, owns_engine=True)
        raw = Path(settings.online_eval.sqlite_path)
        path = raw if raw.is_absolute() else REPO_ROOT / raw
        return cls.from_sqlite_path(path)

    def close(self) -> None:
        if self._owns_engine:
            self._engine.dispose()

    def record_feedback(
        self,
        *,
        message_id: str,
        conversation_id: str,
        customer_id: str,
        rating: FeedbackRating,
        reason: str | None = None,
        trace_id: str | None = None,
        now: datetime | None = None,
    ) -> tuple[FeedbackRecord, bool]:
        """Insert feedback idempotently per message_id. Returns (record, created)."""
        ref_now = _as_utc(now) or datetime.now(UTC)
        clean_reason = redact_pii(reason.strip())[:400] if reason and reason.strip() else None
        with transaction(self._engine) as conn:
            existing = (
                conn.execute(select(turn_feedback).where(turn_feedback.c.message_id == message_id))
                .mappings()
                .first()
            )
            if existing is not None:
                return _row_to_feedback(existing), False
            fb_id = f"fb_{uuid.uuid4().hex[:16]}"
            conn.execute(
                turn_feedback.insert().values(
                    id=fb_id,
                    message_id=message_id,
                    conversation_id=conversation_id,
                    customer_id=customer_id,
                    trace_id=trace_id,
                    rating=rating,
                    reason=clean_reason,
                    created_at=ref_now,
                )
            )
            row = (
                conn.execute(select(turn_feedback).where(turn_feedback.c.id == fb_id))
                .mappings()
                .one()
            )
            return _row_to_feedback(row), True

    def list_feedback(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[FeedbackRecord]:
        with transaction(self._engine) as conn:
            stmt = select(turn_feedback)
            if since is not None:
                stmt = stmt.where(turn_feedback.c.created_at >= _as_utc(since))
            if until is not None:
                stmt = stmt.where(turn_feedback.c.created_at < _as_utc(until))
            stmt = stmt.order_by(turn_feedback.c.created_at.asc())
            return [_row_to_feedback(r) for r in conn.execute(stmt).mappings().all()]

    def record_turn_event(
        self,
        *,
        conversation_id: str,
        customer_id: str,
        trace_id: str | None = None,
        intent: str | None = None,
        path: str | None = None,
        gate_score: float | None = None,
        gate_passed: bool | None = None,
        handoff_reason: str | None = None,
        rewrite_skipped: bool = False,
        tokens_total: int = 0,
        cost_usd: float = 0.0,
        citation_valid: bool | None = None,
        claims_removed: int = 0,
        guardrail_flags: list[str] | None = None,
        question_text: str = "",
        answer_text: str = "",
        now: datetime | None = None,
    ) -> TurnEventRecord:
        ref_now = _as_utc(now) or datetime.now(UTC)
        ev_id = f"ev_{uuid.uuid4().hex[:16]}"
        with transaction(self._engine) as conn:
            conn.execute(
                online_turn_events.insert().values(
                    id=ev_id,
                    conversation_id=conversation_id,
                    customer_id=customer_id,
                    trace_id=trace_id,
                    intent=intent,
                    path=path,
                    gate_score=gate_score,
                    gate_passed=gate_passed,
                    handoff_reason=handoff_reason,
                    rewrite_skipped=rewrite_skipped,
                    tokens_total=max(0, int(tokens_total)),
                    cost_usd=max(0.0, float(cost_usd)),
                    citation_valid=citation_valid,
                    claims_removed=max(0, int(claims_removed)),
                    guardrail_flags=list(guardrail_flags or []),
                    question_redacted=redact_pii(question_text)[:500],
                    answer_redacted=redact_pii(answer_text)[:1000],
                    created_at=ref_now,
                )
            )
            row = (
                conn.execute(select(online_turn_events).where(online_turn_events.c.id == ev_id))
                .mappings()
                .one()
            )
            return _row_to_event(row)

    def list_turn_events(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[TurnEventRecord]:
        with transaction(self._engine) as conn:
            stmt = select(online_turn_events)
            if since is not None:
                stmt = stmt.where(online_turn_events.c.created_at >= _as_utc(since))
            if until is not None:
                stmt = stmt.where(online_turn_events.c.created_at < _as_utc(until))
            stmt = stmt.order_by(online_turn_events.c.created_at.asc())
            return [_row_to_event(r) for r in conn.execute(stmt).mappings().all()]

    def enqueue_review(
        self,
        event: TurnEventRecord,
        *,
        now: datetime | None = None,
    ) -> SampledReviewRecord:
        ref_now = _as_utc(now) or datetime.now(UTC)
        with transaction(self._engine) as conn:
            existing = (
                conn.execute(
                    select(sampled_reviews).where(sampled_reviews.c.turn_event_id == event.id)
                )
                .mappings()
                .first()
            )
            if existing is not None:
                return _row_to_review(existing)
            rev_id = f"rev_{uuid.uuid4().hex[:16]}"
            conn.execute(
                sampled_reviews.insert().values(
                    id=rev_id,
                    turn_event_id=event.id,
                    conversation_id=event.conversation_id,
                    intent=event.intent,
                    gate_score=event.gate_score,
                    question_text=event.question_redacted,
                    answer_text=event.answer_redacted,
                    status="pending",
                    rubric_label=None,
                    reviewer_id=None,
                    note=None,
                    created_at=ref_now,
                    reviewed_at=None,
                )
            )
            row = (
                conn.execute(select(sampled_reviews).where(sampled_reviews.c.id == rev_id))
                .mappings()
                .one()
            )
            return _row_to_review(row)

    def list_reviews(
        self, *, status: ReviewStatus | None = None, limit: int = 100
    ) -> list[SampledReviewRecord]:
        with transaction(self._engine) as conn:
            stmt = select(sampled_reviews)
            if status is not None:
                stmt = stmt.where(sampled_reviews.c.status == status)
            stmt = stmt.order_by(sampled_reviews.c.created_at.desc()).limit(limit)
            return [_row_to_review(r) for r in conn.execute(stmt).mappings().all()]

    def label_review(
        self,
        review_id: str,
        *,
        reviewer_id: str,
        rubric_label: ReviewRubric,
        note: str = "",
        now: datetime | None = None,
    ) -> SampledReviewRecord | None:
        ref_now = _as_utc(now) or datetime.now(UTC)
        with transaction(self._engine) as conn:
            result = conn.execute(
                update(sampled_reviews)
                .where(sampled_reviews.c.id == review_id)
                .values(
                    status="reviewed",
                    rubric_label=rubric_label,
                    reviewer_id=reviewer_id.strip(),
                    note=note.strip(),
                    reviewed_at=ref_now,
                )
            )
            if int(result.rowcount or 0) != 1:
                return None
            row = (
                conn.execute(select(sampled_reviews).where(sampled_reviews.c.id == review_id))
                .mappings()
                .one()
            )
            return _row_to_review(row)
