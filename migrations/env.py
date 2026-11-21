"""Alembic owns the order schema. LangGraph owns its checkpoint tables."""

from alembic import context

from support_agent.config import get_settings
from support_agent.db.engine import make_engine, postgres_url
from support_agent.db.migrate import include_object, require_write_target
from support_agent.orders.tables import metadata
from support_agent.retrieval.index_tables import metadata as index_metadata


def migrate() -> None:
    connection = context.config.attributes.get("connection")
    if connection is not None:
        context.configure(
            connection=connection,
            target_metadata=[metadata, index_metadata],
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    settings = get_settings()
    url = postgres_url(settings)
    if context.is_offline_mode():
        context.configure(url=url, target_metadata=[metadata, index_metadata], literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
        return

    from support_agent.db.migrate import ensure_atlas_schema

    require_write_target(url)
    engine = make_engine(url, settings.db)
    try:
        with engine.begin() as connection:
            ensure_atlas_schema(connection)
            context.configure(
                connection=connection,
                target_metadata=[metadata, index_metadata],
                include_object=include_object,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


migrate()
