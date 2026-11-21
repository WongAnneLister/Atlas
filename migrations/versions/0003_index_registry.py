"""Record immutable index builds, section versions and alias history."""

import sqlalchemy as sa
from alembic import op

metadata = sa.MetaData()

documents = sa.Table(
    "documents",
    metadata,
    sa.Column("doc_id", sa.Text, primary_key=True),
    sa.Column("title", sa.Text, nullable=False),
    sa.Column("source", sa.JSON, nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
)
sections = sa.Table(
    "sections",
    metadata,
    sa.Column("section_id", sa.Text, primary_key=True),
    sa.Column("version", sa.Integer, primary_key=True),
    sa.Column("doc_id", sa.Text, sa.ForeignKey("documents.doc_id"), nullable=False),
    sa.Column("content_hash", sa.Text, nullable=False),
    sa.Column("text", sa.Text, nullable=False),
    sa.Column("metadata", sa.JSON, nullable=False),
    sa.Column("is_deleted", sa.Boolean, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)
index_builds = sa.Table(
    "index_builds",
    metadata,
    sa.Column("build_id", sa.Text, primary_key=True),
    sa.Column("collection", sa.Text, unique=True, nullable=False),
    sa.Column("mode", sa.Text, nullable=False),
    sa.Column("fingerprint", sa.Text, nullable=False),
    sa.Column("embed_model", sa.Text, nullable=False),
    sa.Column("embed_revision", sa.Text, nullable=False),
    sa.Column("embedding_profile", sa.JSON, nullable=False),
    sa.Column("chunker_version", sa.Text, nullable=False),
    sa.Column("docs_hash", sa.Text, nullable=False),
    sa.Column("parent_build_id", sa.Text, sa.ForeignKey("index_builds.build_id")),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("eval_run_id", sa.Text),
    sa.Column("override_reason", sa.Text),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("released_at", sa.DateTime(timezone=True)),
    sa.CheckConstraint("mode IN ('full', 'incremental', 'adopted')", name="index_build_mode"),
    sa.CheckConstraint(
        "status IN ('building', 'built', 'failed', 'released', 'retired', 'dropped')",
        name="index_build_status",
    ),
)
build_sections = sa.Table(
    "build_sections",
    metadata,
    sa.Column("build_id", sa.Text, sa.ForeignKey("index_builds.build_id"), primary_key=True),
    sa.Column("section_id", sa.Text, primary_key=True),
    sa.Column("section_version", sa.Integer, nullable=False),
    sa.Column("content_hash", sa.Text, nullable=False),
    sa.Column("chunk_count", sa.Integer, nullable=False),
    sa.ForeignKeyConstraint(
        ["section_id", "section_version"], ["sections.section_id", "sections.version"]
    ),
)
index_alias = sa.Table(
    "index_alias",
    metadata,
    sa.Column("alias", sa.Text, primary_key=True),
    sa.Column("build_id", sa.Text, sa.ForeignKey("index_builds.build_id")),
    sa.Column("previous_build_id", sa.Text, sa.ForeignKey("index_builds.build_id")),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
)


revision = "0003_index_registry"
down_revision = "0002_refund_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    metadata.create_all(op.get_bind(), checkfirst=False)


def downgrade() -> None:
    metadata.drop_all(op.get_bind(), checkfirst=False)
