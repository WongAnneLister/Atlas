"""Synchronous order API used by later graph tools. It never transfers money."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from json import dumps
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from support_agent.config import REPO_ROOT, OrdersSettings, Settings, get_settings
from support_agent.orders.models import CustomerSummary, Order, RefundRequest, Shipment
from support_agent.orders.sql_repository import OrderRepository


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _refund_id(customer_id: str, order_id: str, key: str | None) -> str:
    value = (
        uuid5(NAMESPACE_URL, dumps(["atlas-refund", customer_id, order_id, key]))
        if key is not None
        else uuid4()
    )
    return f"REF-{value.hex}"


class OrderService:
    def __init__(
        self,
        db_path: Path | None = None,
        settings: OrdersSettings | None = None,
        clock: Callable[[], datetime] = _utc_now,
        *,
        platform: Settings | None = None,
    ) -> None:
        platform = platform or get_settings()
        self.settings = settings or platform.orders
        if db_path is None and platform.db.backend == "sqlite":
            db_path = REPO_ROOT / self.settings.db_path
        self.repository = OrderRepository.from_settings(platform, db_path)
        self.clock = clock

    def close(self) -> None:
        self.repository.close()

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

    def pending_refund_item_ids(
        self,
        order_id: str,
        customer_id: str,
        *,
        idempotency_key: str | None = None,
        legacy_turn_id: str | None = None,
    ) -> list[str]:
        """Item ids held by another request in review; this turn's own write does not count."""
        own = [
            _refund_id(customer_id, order_id, value)
            for value in (idempotency_key, legacy_turn_id)
            if value is not None
        ]
        return self.repository.pending_refund_item_ids(order_id, customer_id, own_request_ids=own)

    def create_refund_request(
        self,
        order_id: str,
        customer_id: str,
        item_ids: list[str],
        reason: str,
        *,
        idempotency_key: str | None = None,
        legacy_turn_id: str | None = None,
        deadline: float | None = None,
    ) -> RefundRequest:
        return self.repository.create_refund_request(
            order_id,
            customer_id,
            item_ids,
            reason,
            _refund_id(customer_id, order_id, idempotency_key),
            self.clock(),
            idempotency_key=idempotency_key,
            deadline=deadline,
            legacy_request_id=(
                _refund_id(customer_id, order_id, legacy_turn_id)
                if legacy_turn_id is not None
                else None
            ),
        )
