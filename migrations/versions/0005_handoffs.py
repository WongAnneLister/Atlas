"""Create handoffs queue table for human takeover and labelled resolutions."""

from alembic import op

from support_agent.handoff.tables import metadata

revision = "0005_handoffs"
down_revision = "0004_customer_memories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    metadata.create_all(op.get_bind(), checkfirst=False)


def downgrade() -> None:
    metadata.drop_all(op.get_bind(), checkfirst=False)
