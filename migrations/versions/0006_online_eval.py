"""Create online_eval tables: turn_feedback, online_turn_events, sampled_reviews."""

from alembic import op

from support_agent.observability.online_tables import metadata

revision = "0006_online_eval"
down_revision = "0005_handoffs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    metadata.create_all(op.get_bind(), checkfirst=False)


def downgrade() -> None:
    metadata.drop_all(op.get_bind(), checkfirst=False)
