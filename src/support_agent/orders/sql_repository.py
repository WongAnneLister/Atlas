"""Order repository shared by SQLite and PostgreSQL."""

from collections.abc import Collection, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from time import monotonic

from sqlalchemy import URL, Connection, Engine, RowMapping, inspect, or_, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

from support_agent.config import Settings
from support_agent.db.engine import make_engine, postgres_url, sqlite_path, transaction
from support_agent.orders import tables
from support_agent.orders.models import (
    CustomerSummary,
    InvalidRefundRequest,
    Order,
    OrderItem,
    OrderNotFound,
    RefundAlreadyPending,
    RefundRequest,
    SeedDataset,
    SeedMetadata,
    Shipment,
)
from support_agent.orders.tables import customers, order_items, orders, shipments


def cents(amount: Decimal) -> int:
    return int(amount * 100)


def _upgrade_sqlite_refund_keys(connection: Connection) -> None:
    columns = inspect(connection).get_columns("refund_requests")
    if any(column["name"] == "idempotency_key" for column in columns):
        return
    connection.exec_driver_sql("ALTER TABLE refund_requests ADD COLUMN idempotency_key TEXT")
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX refund_requests_idempotency_key ON refund_requests (idempotency_key)"
    )


def _pending_items(
    connection: Connection,
    order_id: str,
    *,
    own_request_ids: Collection[str] = (),
    key: str | None = None,
) -> set[str]:
    """Items of the order held by a request in review, other than this turn's own write."""
    requests, items = tables.refund_requests, tables.refund_request_items
    statement = (
        select(items.c.item_id)
        .join(requests, requests.c.request_id == items.c.request_id)
        .where(items.c.order_id == order_id, requests.c.status == "pending_review")
    )
    if own_request_ids:
        statement = statement.where(requests.c.request_id.not_in(list(own_request_ids)))
    if key is not None:
        statement = statement.where(
            or_(requests.c.idempotency_key.is_(None), requests.c.idempotency_key != key)
        )
    return set(connection.execute(statement).scalars())


def _refund_time_left(deadline: float) -> float:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError("Refund transaction deadline exceeded")
    return remaining


def _check_refund_deadline(connection: Connection, deadline: float) -> None:
    remaining = _refund_time_left(deadline)
    if connection.dialect.name == "postgresql":
        timeout_ms = max(1, int(remaining * 1000))
        connection.exec_driver_sql(f"SET LOCAL statement_timeout = {timeout_ms}")
        _refund_time_left(deadline)


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

    @contextmanager
    def _refund_transaction(self, deadline: float | None) -> Iterator[Connection]:
        if deadline is not None:
            _refund_time_left(deadline)
        with self.connection(write=True) as connection:
            if deadline is not None:
                _check_refund_deadline(connection, deadline)
            yield connection
            if deadline is not None:
                _check_refund_deadline(connection, deadline)

    def replace(self, dataset: SeedDataset) -> None:
        """Reset known mock tables and insert the validated dataset in one transaction."""
        with self.connection(create=True, write=True) as connection:
            if self.engine.dialect.name == "sqlite":
                tables.metadata.create_all(connection)
                _upgrade_sqlite_refund_keys(connection)
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

    def customer_email(self, customer_id: str) -> str | None:
        statement = select(customers.c.email).where(customers.c.customer_id == customer_id)
        with self.connection() as connection:
            return connection.execute(statement).scalar_one_or_none()

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

    def pending_refund_item_ids(
        self,
        order_id: str,
        customer_id: str,
        *,
        own_request_ids: Collection[str] = (),
    ) -> list[str]:
        # No key filter here: a legacy SQLite file may lack the column until its next write.
        with self.connection() as connection:
            self._owned_order(connection, order_id, customer_id)
            return sorted(_pending_items(connection, order_id, own_request_ids=own_request_ids))

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
        *,
        idempotency_key: str | None = None,
        legacy_request_id: str | None = None,
        deadline: float | None = None,
    ) -> RefundRequest:
        with self._refund_transaction(deadline) as connection:
            # Ownership is checked before any request validation or write.
            order = self._owned_order(connection, order_id, customer_id)
            # Serialise writers per order so two chats cannot both pass the pending check.
            # SQLite already holds its write lock from BEGIN IMMEDIATE.
            connection.execute(
                select(orders.c.order_id).where(orders.c.order_id == order_id).with_for_update()
            )
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
            if connection.dialect.name == "sqlite":
                _upgrade_sqlite_refund_keys(connection)
            if legacy_request_id is not None:
                legacy = self._refund_row(connection, legacy_request_id)
                if legacy is not None and legacy["idempotency_key"] in (None, idempotency_key):
                    return self._existing_refund(connection, legacy, request, idempotency_key)
            pending = _pending_items(
                connection, order_id, own_request_ids=[request_id], key=idempotency_key
            )
            if pending & set(item_ids):
                raise RefundAlreadyPending("An item already has a refund request in review")

            insert = postgres_insert if connection.dialect.name == "postgresql" else sqlite_insert
            statement = insert(table).on_conflict_do_nothing().returning(table.c.request_id)
            values = request.model_dump(exclude={"item_ids"})
            inserted = connection.execute(
                statement, {**values, "idempotency_key": idempotency_key}
            ).scalar_one_or_none()
            if inserted is None:
                row = self._refund_row(connection, request_id, idempotency_key)
                return self._existing_refund(connection, row, request, idempotency_key)
            connection.execute(
                tables.refund_request_items.insert(),
                [
                    {"request_id": request_id, "order_id": order_id, "item_id": item_id}
                    for item_id in item_ids
                ],
            )
            return request

    @staticmethod
    def _refund_row(
        connection: Connection, request_id: str, key: str | None = None
    ) -> RowMapping | None:
        table = tables.refund_requests
        query = select(table).with_for_update()
        if key is not None:
            row = (
                connection.execute(query.where(table.c.idempotency_key == key))
                .mappings()
                .one_or_none()
            )
            if row is not None:
                return row
        return (
            connection.execute(query.where(table.c.request_id == request_id))
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def _existing_refund(
        connection: Connection,
        row: RowMapping | None,
        request: RefundRequest,
        key: str | None,
    ) -> RefundRequest:
        if (
            row is None
            or row["order_id"] != request.order_id
            or row["customer_id"] != request.customer_id
            or row["reason"] != request.reason
            or row["idempotency_key"] not in (None, key)
        ):
            raise InvalidRefundRequest("Refund request key was already used")

        request_id = row["request_id"]
        items = tables.refund_request_items
        item_ids = (
            connection.execute(select(items.c.item_id).where(items.c.request_id == request_id))
            .scalars()
            .all()
        )
        if set(item_ids) != set(request.item_ids):
            raise InvalidRefundRequest("Refund request key was already used")

        if key is not None and row["idempotency_key"] is None:
            # A matching request predates the unique key. Claim it for future replays.
            table = tables.refund_requests
            try:
                connection.execute(
                    table.update()
                    .where(table.c.request_id == request_id)
                    .values(idempotency_key=key)
                )
            except IntegrityError:
                raise InvalidRefundRequest("Refund request key was already used") from None
        return RefundRequest.model_validate({**row, "item_ids": request.item_ids})

    def seed_metadata(self) -> SeedMetadata:
        table = tables.seed_metadata
        with self.connection() as connection:
            value = connection.execute(select(table.c.value).where(table.c.key == "seed")).scalar()
            if value is None:
                raise ValueError("Database has no seed metadata")
            return SeedMetadata.model_validate_json(value)
