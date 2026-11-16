"""Synchronous order API used by later graph tools. It never transfers money."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from support_agent.config import REPO_ROOT, OrdersSettings, get_settings
from support_agent.orders.db import OrderRepository
from support_agent.orders.models import CustomerSummary, Order, RefundRequest, Shipment


def _utc_now() -> datetime:
    return datetime.now(UTC)


class OrderService:
    def __init__(
        self,
        db_path: Path | None = None,
        settings: OrdersSettings | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.settings = settings or get_settings().orders
        self.repository = OrderRepository(db_path or REPO_ROOT / self.settings.db_path)
        self.clock = clock

    def list_customers(self, limit: int) -> list[CustomerSummary]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        return self.repository.list_customers(limit)

    def customer_exists(self, customer_id: str) -> bool:
        return self.repository.customer_exists(customer_id)

    def get_order(self, order_id: str, customer_id: str) -> Order:
        return self.repository.get_order(order_id, customer_id)

    def list_recent_orders(self, customer_id: str, limit: int | None = None) -> list[Order]:
        effective_limit = self.settings.recent_limit if limit is None else limit
        if (
            isinstance(effective_limit, bool)
            or not isinstance(effective_limit, int)
            or effective_limit <= 0
        ):
            raise ValueError("limit must be a positive integer")
        return self.repository.list_recent_orders(customer_id, effective_limit)

    def get_tracking(self, order_id: str, customer_id: str) -> Shipment | None:
        return self.repository.get_tracking(order_id, customer_id)

    def create_refund_request(
        self,
        order_id: str,
        customer_id: str,
        item_ids: list[str],
        reason: str,
    ) -> RefundRequest:
        return self.repository.create_refund_request(
            order_id,
            customer_id,
            item_ids,
            reason,
            f"REF-{uuid4().hex}",
            self.clock(),
        )
