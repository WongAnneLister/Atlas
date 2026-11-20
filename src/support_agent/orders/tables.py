"""Shared mock-order schema for SQLite and PostgreSQL."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Dialect,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.types import TypeDecorator


class _SQLiteTimestamp(TypeDecorator[datetime]):
    """Keep SQLite's existing ISO timestamps, including the UTC offset."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> str | None:
        return value.isoformat().replace("+00:00", "Z") if value is not None else None

    def process_result_value(self, value: str | None, dialect: Dialect) -> datetime | None:
        return datetime.fromisoformat(value) if value is not None else None


metadata = MetaData()
_timestamp = DateTime(timezone=True).with_variant(_SQLiteTimestamp(), "sqlite")
_flag = Boolean(create_constraint=True)
customers = Table(
    "customers",
    metadata,
    Column("customer_id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("email", Text, nullable=False, unique=True),
    CheckConstraint("email LIKE '%@example.com'"),
)
orders = Table(
    "orders",
    metadata,
    Column("order_id", Text, primary_key=True),
    Column("customer_id", Text, ForeignKey("customers.customer_id"), nullable=False),
    Column("status", Text, nullable=False),
    Column("order_date", Date, nullable=False),
    Column("delivered_at", Date),
    Column("currency", Text, nullable=False),
    Column("total_cents", BigInteger, nullable=False),
    Column("paid_with_coupon", _flag, nullable=False),
    Column("coupon_code", Text),
    CheckConstraint(
        "status IN ('pending', 'paid', 'shipped', 'in_transit', 'delivered', 'cancelled', "
        "'refunded', 'partially_refunded')"
    ),
    CheckConstraint("total_cents >= 0"),
    CheckConstraint("paid_with_coupon = (coupon_code IS NOT NULL)"),
    UniqueConstraint("order_id", "customer_id"),
)
Index(
    "orders_customer_date",
    orders.c.customer_id,
    orders.c.order_date.desc(),
    orders.c.order_id.desc(),
)

order_items = Table(
    "order_items",
    metadata,
    Column("item_id", Text, primary_key=True),
    Column("order_id", Text, ForeignKey("orders.order_id"), nullable=False),
    Column("product_id", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("category", Text, nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("unit_price_cents", BigInteger, nullable=False),
    Column("final_sale", _flag, nullable=False),
    Column("refunded_quantity", Integer, nullable=False),
    CheckConstraint("quantity > 0"),
    CheckConstraint("unit_price_cents >= 0"),
    CheckConstraint("refunded_quantity >= 0 AND refunded_quantity <= quantity"),
    UniqueConstraint("item_id", "order_id"),
)
Index("items_order", order_items.c.order_id)

shipments = Table(
    "shipments",
    metadata,
    Column("order_id", Text, ForeignKey("orders.order_id"), primary_key=True),
    Column("carrier", Text, nullable=False),
    Column("tracking_number", Text, nullable=False, unique=True),
    Column("status", Text, nullable=False),
    Column("shipped_at", Date, nullable=False),
    Column("expected_delivery", Date, nullable=False),
    Column("last_event_at", _timestamp, nullable=False),
    Column("last_event", Text, nullable=False),
    CheckConstraint("status IN ('shipped', 'in_transit', 'delayed', 'delivered')"),
)
refund_requests = Table(
    "refund_requests",
    metadata,
    Column("request_id", Text, primary_key=True),
    Column("order_id", Text, nullable=False),
    Column("customer_id", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("idempotency_key", Text),
    Column("status", Text, nullable=False),
    Column("created_at", _timestamp, nullable=False),
    CheckConstraint("length(trim(reason)) > 0"),
    CheckConstraint("status = 'pending_review'"),
    ForeignKeyConstraint(["order_id", "customer_id"], ["orders.order_id", "orders.customer_id"]),
    UniqueConstraint("request_id", "order_id"),
    UniqueConstraint("idempotency_key", name="refund_requests_idempotency_key"),
)
refund_request_items = Table(
    "refund_request_items",
    metadata,
    Column("request_id", Text, primary_key=True),
    Column("order_id", Text, nullable=False),
    Column("item_id", Text, primary_key=True),
    ForeignKeyConstraint(
        ["request_id", "order_id"], ["refund_requests.request_id", "refund_requests.order_id"]
    ),
    ForeignKeyConstraint(["item_id", "order_id"], ["order_items.item_id", "order_items.order_id"]),
)
seed_metadata = Table(
    "seed_metadata",
    metadata,
    Column("key", Text, primary_key=True),
    Column("value", Text, nullable=False),
)
