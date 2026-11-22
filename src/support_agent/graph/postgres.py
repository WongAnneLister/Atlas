"""PostgreSQL checkpoint connections and explicit state serialization."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from sqlalchemy import Connection as SqlConnection

from support_agent.config import Settings
from support_agent.db.engine import postgres_url
from support_agent.gate.evidence import GateResult
from support_agent.graph.coverage import CoverageAnswer
from support_agent.graph.handoff import HandoffPayload, HandoffReason
from support_agent.graph.intents import Intent, Path
from support_agent.graph.state import CitationRecord
from support_agent.orders.models import Order, OrderItem, OrderStatus, RefundRequest, Shipment
from support_agent.reliability.events import ReliabilityEvent
from support_agent.retrieval.filters import RetrievalFilters
from support_agent.retrieval.types import RetrievedChunk

if TYPE_CHECKING:
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg import Connection


def checkpoint_serializer() -> JsonPlusSerializer:
    state_types = (
        CitationRecord,
        CoverageAnswer,
        GateResult,
        HandoffPayload,
        HandoffReason,
        Intent,
        Order,
        OrderItem,
        OrderStatus,
        Path,
        RefundRequest,
        ReliabilityEvent,
        RetrievalFilters,
        RetrievedChunk,
        Shipment,
    )
    return JsonPlusSerializer(
        pickle_fallback=False,
        allowed_msgpack_modules=[(cls.__module__, cls.__name__) for cls in state_types],
    )


@contextmanager
def postgres_saver(settings: Settings) -> Iterator["PostgresSaver"]:
    url = postgres_url(settings).set(drivername="postgresql")
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool
    except ImportError as error:
        raise RuntimeError("Postgres checkpoints require the postgres extra") from error

    pool: ConnectionPool[Connection[dict[str, Any]]] = ConnectionPool(
        conninfo=url.render_as_string(hide_password=False),
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
            "connect_timeout": settings.db.connect_timeout_s,
        },
        min_size=0,
        max_size=settings.db.pool_size + settings.db.max_overflow,
        timeout=settings.db.pool_timeout_s,
        open=True,
    )
    with pool:
        yield PostgresSaver(pool, serde=checkpoint_serializer())


def checkpoint_migrations_at_head(connection: SqlConnection) -> bool:
    from langgraph.checkpoint.postgres import PostgresSaver

    applied = connection.exec_driver_sql("SELECT max(v) FROM checkpoint_migrations").scalar_one()
    return bool(applied == len(PostgresSaver.MIGRATIONS) - 1)
