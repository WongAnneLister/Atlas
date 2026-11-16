"""Small SQLite repository. Currency amounts are stored as integer cents."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path

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

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def cents(amount: Decimal) -> int:
    return int(amount * 100)


class OrderRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    @contextmanager
    def connection(self, *, create: bool = False) -> Iterator[sqlite3.Connection]:
        if create:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        elif not self.db_path.is_file():
            raise FileNotFoundError("Order database missing; run make data-orders")
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def replace(self, dataset: SeedDataset) -> None:
        """Reset known mock tables and insert the validated dataset in one transaction."""
        with self.connection(create=True) as connection:
            connection.executescript("BEGIN;\n" + SCHEMA_PATH.read_text(encoding="utf-8"))
            connection.executemany(
                "INSERT INTO customers VALUES (:customer_id, :name, :email)",
                [customer.model_dump() for customer in dataset.customers],
            )
            for order in dataset.orders:
                data = order.model_dump(mode="json", exclude={"items", "total"})
                data["total_cents"] = cents(order.total)
                connection.execute(
                    "INSERT INTO orders VALUES (:order_id, :customer_id, :status, :order_date, "
                    ":delivered_at, :currency, :total_cents, :paid_with_coupon, :coupon_code)",
                    data,
                )
                for item in order.items:
                    item_data = item.model_dump(mode="json", exclude={"unit_price"})
                    item_data.update(
                        order_id=order.order_id, unit_price_cents=cents(item.unit_price)
                    )
                    connection.execute(
                        "INSERT INTO order_items VALUES (:item_id, :order_id, :product_id, :model, "
                        ":name, :category, :quantity, :unit_price_cents, :final_sale, "
                        ":refunded_quantity)",
                        item_data,
                    )
            connection.executemany(
                "INSERT INTO shipments VALUES (:order_id, :carrier, :tracking_number, :status, "
                ":shipped_at, :expected_delivery, :last_event_at, :last_event)",
                [shipment.model_dump(mode="json") for shipment in dataset.shipments],
            )
            connection.execute(
                "INSERT INTO seed_metadata VALUES ('seed', ?)",
                (dataset.metadata.model_dump_json(),),
            )

    def _owned_order(
        self,
        connection: sqlite3.Connection,
        order_id: str,
        customer_id: str,
    ) -> Order:
        row = connection.execute(
            "SELECT * FROM orders WHERE order_id = ? AND customer_id = ?",
            (order_id, customer_id),
        ).fetchone()
        if row is None:
            raise OrderNotFound("Order not found")
        items = []
        for item in connection.execute(
            "SELECT * FROM order_items WHERE order_id = ? ORDER BY item_id",
            (order_id,),
        ):
            values = dict(item)
            values["unit_price"] = Decimal(values.pop("unit_price_cents")) / 100
            items.append(OrderItem.model_validate(values))
        values = dict(row)
        values["total"] = Decimal(values.pop("total_cents")) / 100
        return Order.model_validate({**values, "items": items})

    def list_customers(self, limit: int) -> list[CustomerSummary]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT customer_id, name FROM customers ORDER BY customer_id LIMIT ?", (limit,)
            )
            return [
                CustomerSummary(customer_id=row["customer_id"], name=row["name"]) for row in rows
            ]

    def customer_exists(self, customer_id: str) -> bool:
        with self.connection() as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM customers WHERE customer_id = ?", (customer_id,)
                ).fetchone()
                is not None
            )

    def get_order(self, order_id: str, customer_id: str) -> Order:
        with self.connection() as connection:
            return self._owned_order(connection, order_id, customer_id)

    def list_recent_orders(self, customer_id: str, limit: int) -> list[Order]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT order_id FROM orders WHERE customer_id = ? "
                "ORDER BY order_date DESC, order_id DESC LIMIT ?",
                (customer_id, limit),
            ).fetchall()
            return [self._owned_order(connection, row["order_id"], customer_id) for row in rows]

    def get_tracking(self, order_id: str, customer_id: str) -> Shipment | None:
        with self.connection() as connection:
            self._owned_order(connection, order_id, customer_id)
            row = connection.execute(
                "SELECT * FROM shipments WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            return Shipment.model_validate(dict(row)) if row is not None else None

    def create_refund_request(
        self,
        order_id: str,
        customer_id: str,
        item_ids: list[str],
        reason: str,
        request_id: str,
        created_at: datetime,
    ) -> RefundRequest:
        with self.connection() as connection:
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
            data = request.model_dump(mode="json", exclude={"item_ids"})
            connection.execute(
                "INSERT INTO refund_requests VALUES (:request_id, :order_id, :customer_id, "
                ":reason, :status, :created_at)",
                data,
            )
            connection.executemany(
                "INSERT INTO refund_request_items VALUES (?, ?, ?)",
                [(request_id, order_id, item_id) for item_id in request.item_ids],
            )
            return request

    def seed_metadata(self) -> SeedMetadata:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT value FROM seed_metadata WHERE key = 'seed'"
            ).fetchone()
            if row is None:
                raise ValueError("Database has no seed metadata")
            return SeedMetadata.model_validate_json(row["value"])
