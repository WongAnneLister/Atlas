"""SQLAlchemy table definition for governed long-term customer memories."""

from __future__ import annotations

import sqlalchemy as sa

metadata = sa.MetaData()

customer_memories = sa.Table(
    "customer_memories",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("customer_id", sa.Text, nullable=False),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("content", sa.Text, nullable=False),
    sa.Column("structured", sa.JSON, nullable=False),
    sa.Column("embedding", sa.JSON, nullable=True),
    sa.Column("idempotency_key", sa.Text, nullable=True),
    sa.Column("source_conversation_id", sa.Text, nullable=False),
    sa.Column("source_turn", sa.Integer, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("confidence", sa.Float, nullable=False),
    sa.Column("superseded_by", sa.Text, nullable=True),
    sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint(
        "kind IN ('open_issue', 'preference', 'product_owned', 'past_resolution')",
        name="customer_memories_kind_check",
    ),
    sa.CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="customer_memories_conf"),
    sa.CheckConstraint("length(trim(customer_id)) > 0", name="customer_memories_customer_nonempty"),
    sa.Index("ix_customer_memories_scope", "customer_id", "deleted_at", "expires_at"),
    sa.UniqueConstraint("customer_id", "idempotency_key", name="uq_customer_memories_idempotency"),
)
