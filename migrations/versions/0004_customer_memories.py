"""Create customer_memories table with Postgres row-level security."""

import sqlalchemy as sa
from alembic import op

from support_agent.memory.long_term.tables import metadata

revision = "0004_customer_memories"
down_revision = "0003_index_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    metadata.create_all(bind, checkfirst=False)
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("ALTER TABLE customer_memories ENABLE ROW LEVEL SECURITY"))
        op.execute(sa.text("ALTER TABLE customer_memories FORCE ROW LEVEL SECURITY"))
        op.execute(
            sa.text(
                "CREATE POLICY customer_memories_isolation ON customer_memories "
                "USING ("
                "  NULLIF(current_setting('app.customer_id', true), '') IS NOT NULL "
                "  AND customer_id = current_setting('app.customer_id', true)"
                ") "
                "WITH CHECK ("
                "  NULLIF(current_setting('app.customer_id', true), '') IS NOT NULL "
                "  AND customer_id = current_setting('app.customer_id', true)"
                ")"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text("DROP POLICY IF EXISTS customer_memories_isolation ON customer_memories")
        )
    metadata.drop_all(bind, checkfirst=False)
