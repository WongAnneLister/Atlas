"""Order repository shared by SQLite and PostgreSQL."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import URL, Connection, Engine, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from support_agent.config import Settings
from support_agent.db.engine import make_engine, postgres_url, sqlite_path, transaction
from support_agent.orders import tables
from support_agent.orders.models import (
    CustomerSummary,
    InvalidRefundRequest,
    Order,
    OrderItem,
    OrderNotFound,
    RefundRequest,
    SeedDataset,
    SeedMetadata,
    Shipment,
)
from support_agent.orders.tables import customers, order_items, orders, shipments


def cents(amount: Decimal) -> int:
    return int(amount * 100)


class OrderRepository:
    def __init__(self, engine: Engine, db_path: Path | None = None) -> None:
        self.engine = engine
        self.db_path = db_path

    @classmethod
    def from_settings(cls, settings: Settings, db_path: Path | None = None) -> "OrderRepository":
        if db_path is None and settings.db.backend == "postgres":
            return cls(make_engine(postgres_url(settings), settings.db))
        path = db_path or sqlite_path(settings)
        return cls(make_engine(URL.create("sqlite", database=str(path)), settings.db), path)

    def close(self) -> None:
        self.engine.dispose()

    @contextmanager
    def connection(self, *, create: bool = False, write: bool = False) -> Iterator[Connection]:
        if self.db_path is not None:
            if create:
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
            elif not self.db_path.is_file():
                raise FileNotFoundError("Order database missing; run make data-orders")
        with transaction(self.engine, write=write) as connection:
            yield connection

    def replace(self, dataset: SeedDataset) -> None:
        """Reset known mock tables and insert the validated dataset in one transaction."""
        with self.connection(create=True, write=True) as connection:
            if self.engine.dialect.name == "sqlite":
                tables.metadata.create_all(connection)
            for table in reversed(tables.metadata.sorted_tables):
                connection.execute(table.delete())
            if dataset.customers:
                connection.execute(
                    customers.insert(), [row.model_dump() for row in dataset.customers]
                )
            order_rows = [
                {
                    **order.model_dump(exclude={"items", "total"}),
                    "total_cents": cents(order.total),
                }
                for order in dataset.orders
            ]
            connection.execute(orders.insert(), order_rows)
            item_rows = [
                {
                    **item.model_dump(exclude={"unit_price"}),
                    "order_id": order.order_id,
                    "unit_price_cents": cents(item.unit_price),
                }
                for order in dataset.orders
                for item in order.items
            ]
            connection.execute(order_items.insert(), item_rows)
            if dataset.shipments:
                connection.execute(
                    shipments.insert(), [row.model_dump() for row in dataset.shipments]
                )
            connection.execute(
                tables.seed_metadata.insert().values(
                    key="seed", value=dataset.metadata.model_dump_json()
                )
            )

    def _owned_order(self, connection: Connection, order_id: str, customer_id: str) -> Order:
        row = (
            connection.execute(
                select(orders).where(
                    orders.c.order_id == order_id, orders.c.customer_id == customer_id
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise OrderNotFound("Order not found")
        items = []
        statement = select(order_items).where(order_items.c.order_id == order_id)
        for item in connection.execute(statement.order_by(order_items.c.item_id)).mappings():
            values = dict(item)
            values["unit_price"] = Decimal(values.pop("unit_price_cents")) / 100
            items.append(OrderItem.model_validate(values))
        values = dict(row)
        values["total"] = Decimal(values.pop("total_cents")) / 100
        return Order.model_validate({**values, "items": items})

    def list_customers(self, limit: int) -> list[CustomerSummary]:
        statement = select(customers.c.customer_id, customers.c.name).order_by(
            customers.c.customer_id
        )
        with self.connection() as connection:
            return [
                CustomerSummary.model_validate(dict(row))
                for row in connection.execute(statement.limit(limit)).mappings()
            ]

    def customer_exists(self, customer_id: str) -> bool:
        statement = select(customers.c.customer_id).where(customers.c.customer_id == customer_id)
        with self.connection() as connection:
            return connection.execute(statement).first() is not None

    def get_order(self, order_id: str, customer_id: str) -> Order:
        with self.connection() as connection:
            return self._owned_order(connection, order_id, customer_id)

    def list_recent_orders(self, customer_id: str, limit: int) -> list[Order]:
        statement = (
            select(orders.c.order_id)
            .where(orders.c.customer_id == customer_id)
            .order_by(orders.c.order_date.desc(), orders.c.order_id.desc())
            .limit(limit)
        )
        with self.connection() as connection:
            ids = connection.execute(statement).scalars().all()
            return [self._owned_order(connection, order_id, customer_id) for order_id in ids]

    def get_tracking(self, order_id: str, customer_id: str) -> Shipment | None:
        with self.connection() as connection:
            self._owned_order(connection, order_id, customer_id)
            row = (
                connection.execute(select(shipments).where(shipments.c.order_id == order_id))
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            values = dict(row)
            if self.engine.dialect.name == "postgresql":
                values["last_event_at"] = values["last_event_at"].astimezone(UTC)
            return Shipment.model_validate(values)

    def create_refund_request(
        self,
        order_id: str,
        customer_id: str,
        item_ids: list[str],
        reason: str,
        request_id: str,
        created_at: datetime,
    ) -> RefundRequest:
        with self.connection(write=True) as connection:
            # Ownership is checked before any request validation or write.
            order = self._owned_order(connection, order_id, customer_id)
            valid_ids = {item.item_id for item in order.items}
            if (
                not item_ids
                or len(set(item_ids)) != len(item_ids)
                or not set(item_ids) <= valid_ids
            ):
                raise InvalidRefundRequest("Choose unique item ids from this order")
            if not reason.strip():
                raise InvalidRefundRequest("A refund request needs a reason")
            request = RefundRequest(
                request_id=request_id,
                order_id=order_id,
                customer_id=customer_id,
                item_ids=item_ids,
                reason=reason,
                status="pending_review",
                created_at=created_at,
            )
            table = tables.refund_requests
            insert = postgres_insert if self.engine.dialect.name == "postgresql" else sqlite_insert
            statement = insert(table).on_conflict_do_nothing(index_elements=[table.c.request_id])
            inserted = connection.execute(
                statement.returning(table.c.request_id), request.model_dump(exclude={"item_ids"})
            ).scalar_one_or_none()
            if inserted is None:
                return self._existing_refund(connection, request)
            connection.execute(
                tables.refund_request_items.insert(),
                [
                    {"request_id": request_id, "order_id": order_id, "item_id": item_id}
                    for item_id in item_ids
                ],
            )
            return request

    @staticmethod
    def _existing_refund(connection: Connection, request: RefundRequest) -> RefundRequest:
        table = tables.refund_requests
        row = (
            connection.execute(
                select(table).where(
                    table.c.request_id == request.request_id,
                    table.c.order_id == request.order_id,
                    table.c.customer_id == request.customer_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        items = tables.refund_request_items
        item_ids = (
            connection.execute(
                select(items.c.item_id).where(items.c.request_id == request.request_id)
            )
            .scalars()
            .all()
        )
        if row is None or row["reason"] != request.reason or set(item_ids) != set(request.item_ids):
            raise InvalidRefundRequest("Refund request key was already used")
        return RefundRequest.model_validate({**row, "item_ids": request.item_ids})

    def seed_metadata(self) -> SeedMetadata:
        table = tables.seed_metadata
        with self.connection() as connection:
            value = connection.execute(select(table.c.value).where(table.c.key == "seed")).scalar()
            if value is None:
                raise ValueError("Database has no seed metadata")
            return SeedMetadata.model_validate_json(value)
