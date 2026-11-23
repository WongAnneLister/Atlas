"""SQLAlchemy tables for online feedback, turn telemetry, and sampled human reviews."""

from __future__ import annotations

import sqlalchemy as sa

metadata = sa.MetaData()

turn_feedback = sa.Table(
    "turn_feedback",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("message_id", sa.Text, nullable=False, unique=True),
    sa.Column("conversation_id", sa.Text, nullable=False),
    sa.Column("customer_id", sa.Text, nullable=False),
    sa.Column("trace_id", sa.Text, nullable=True),
    sa.Column("rating", sa.Text, nullable=False),
    sa.Column("reason", sa.Text, nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("rating IN ('up', 'down')", name="turn_feedback_rating_check"),
    sa.Index("ix_turn_feedback_created", "created_at"),
)

online_turn_events = sa.Table(
    "online_turn_events",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("conversation_id", sa.Text, nullable=False),
    sa.Column("customer_id", sa.Text, nullable=False),
    sa.Column("trace_id", sa.Text, nullable=True),
    sa.Column("intent", sa.Text, nullable=True),
    sa.Column("path", sa.Text, nullable=True),
    sa.Column("gate_score", sa.Float, nullable=True),
    sa.Column("gate_passed", sa.Boolean, nullable=True),
    sa.Column("handoff_reason", sa.Text, nullable=True),
    sa.Column("rewrite_skipped", sa.Boolean, nullable=False),
    sa.Column("tokens_total", sa.Integer, nullable=False),
    sa.Column("cost_usd", sa.Float, nullable=False),
    sa.Column("citation_valid", sa.Boolean, nullable=True),
    sa.Column("claims_removed", sa.Integer, nullable=False),
    sa.Column("guardrail_flags", sa.JSON, nullable=False),
    sa.Column("question_redacted", sa.Text, nullable=False),
    sa.Column("answer_redacted", sa.Text, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Index("ix_online_turn_events_created", "created_at"),
)

sampled_reviews = sa.Table(
    "sampled_reviews",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("turn_event_id", sa.Text, nullable=False, unique=True),
    sa.Column("conversation_id", sa.Text, nullable=False),
    sa.Column("intent", sa.Text, nullable=True),
    sa.Column("gate_score", sa.Float, nullable=True),
    sa.Column("question_text", sa.Text, nullable=False),
    sa.Column("answer_text", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("rubric_label", sa.Text, nullable=True),
    sa.Column("reviewer_id", sa.Text, nullable=True),
    sa.Column("note", sa.Text, nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('pending', 'reviewed')", name="sampled_reviews_status_check"),
    sa.CheckConstraint(
        "rubric_label IS NULL OR rubric_label IN ("
        "'correct', 'partially_correct', 'wrong', 'should_have_handed_off')",
        name="sampled_reviews_rubric_check",
    ),
    sa.Index("ix_sampled_reviews_status_created", "status", "created_at"),
)
