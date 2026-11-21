"""Enforce unique refund idempotency keys while retaining existing requests.

Revision ID: 0002_refund_idempotency
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_refund_idempotency"
down_revision = "0001_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("refund_requests", sa.Column("idempotency_key", sa.Text(), nullable=True))
    if op.get_context().dialect.name == "sqlite":
        op.create_index(
            "refund_requests_idempotency_key", "refund_requests", ["idempotency_key"], unique=True
        )
    else:
        op.create_unique_constraint(
            "refund_requests_idempotency_key", "refund_requests", ["idempotency_key"]
        )


def downgrade() -> None:
    if op.get_context().dialect.name == "sqlite":
        op.drop_index("refund_requests_idempotency_key", table_name="refund_requests")
    else:
        op.drop_constraint("refund_requests_idempotency_key", "refund_requests", type_="unique")
    op.drop_column("refund_requests", "idempotency_key")
