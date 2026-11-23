"""SQLAlchemy table definition for the human handoff queue."""

from __future__ import annotations

import sqlalchemy as sa

metadata = sa.MetaData()

handoffs = sa.Table(
    "handoffs",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("conversation_id", sa.Text, nullable=False),
    sa.Column("customer_id", sa.Text, nullable=False),
    sa.Column("reason", sa.Text, nullable=False),
    sa.Column("priority", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("claimed_by", sa.Text, nullable=True),
    sa.Column("payload", sa.JSON, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("resolution_label", sa.Text, nullable=True),
    sa.Column("resolution_note", sa.Text, nullable=True),
    sa.Column("idempotency_key", sa.Text, nullable=True, unique=True),
    sa.CheckConstraint("priority IN ('high', 'normal', 'low')", name="handoffs_priority_check"),
    sa.CheckConstraint("status IN ('open', 'claimed', 'resolved')", name="handoffs_status_check"),
    sa.CheckConstraint(
        "resolution_label IS NULL OR resolution_label IN ("
        "'kb_gap', 'retrieval_miss', 'gate_too_strict', "
        "'correct_handoff', 'policy_exception', 'abuse')",
        name="handoffs_resolution_label_check",
    ),
    sa.Index("ix_handoffs_status_priority_created", "status", "priority", "created_at"),
    sa.Index("ix_handoffs_conversation_status", "conversation_id", "status"),
)
