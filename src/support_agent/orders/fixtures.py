"""Catalog inputs and named demonstration cases for the deterministic order seed."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel

from support_agent.config import OrdersSettings, SeedProduct, Settings
from support_agent.orders.models import Customer, Order, OrderItem, OrderStatus, Shipment


class Scenario(BaseModel):
    name: str
    status: OrderStatus
    delivery_age: int | None = None
    final_sale: bool = False
    coupon: bool = False
    delayed: bool = False


def scenarios(settings: OrdersSettings) -> list[Scenario]:
    recent = settings.delivery_ages_days[0]
    cases = [
        Scenario(
            name=f"delivered_{age}_days",
            status=OrderStatus.DELIVERED,
            delivery_age=age,
        )
        for age in dict.fromkeys(settings.delivery_ages_days)
    ]
    cases.extend(
        [
            Scenario(
                name="final_sale",
                status=OrderStatus.DELIVERED,
                delivery_age=recent,
                final_sale=True,
            ),
            Scenario(name="coupon", status=OrderStatus.DELIVERED, delivery_age=recent, coupon=True),
            Scenario(
                name="partially_refunded",
                status=OrderStatus.PARTIALLY_REFUNDED,
                delivery_age=recent,
            ),
            Scenario(name="cancelled", status=OrderStatus.CANCELLED),
            Scenario(name="delayed_tracking", status=OrderStatus.IN_TRANSIT, delayed=True),
            Scenario(name="pending", status=OrderStatus.PENDING),
            Scenario(name="paid", status=OrderStatus.PAID),
            Scenario(name="shipped", status=OrderStatus.SHIPPED),
            Scenario(name="in_transit", status=OrderStatus.IN_TRANSIT),
            Scenario(name="refunded", status=OrderStatus.REFUNDED, delivery_age=recent),
        ]
    )
    return cases


def load_products(settings: Settings, catalog_path: Path) -> tuple[list[SeedProduct], str]:
    if not catalog_path.exists():
        return sorted(settings.orders.fallback_products, key=lambda p: p.product_id), "built_in"
    products: list[SeedProduct] = []
    for line in catalog_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if not record.get("category"):
            model = record["model"]
            categories = settings.data.docs.product_categories
            record["category"] = next(
                (category for prefix, category in categories.items() if model.startswith(prefix)),
                categories["monitor"],
            )
        products.append(SeedProduct.model_validate(record))
    if not products or len({p.product_id for p in products}) != len(products):
        raise ValueError("Catalog must have products with unique product ids")
    return sorted(products, key=lambda p: p.product_id), "processed_catalog"


TIME_SENSITIVE_CUSTOMER = Customer(
    customer_id="CUST-TS01",
    name="Policy Demo Customer",
    email="policy.demo@example.com",
)
TIME_SENSITIVE_DEV_ORDERS = {
    "ORD-999996": date(2026, 8, 20),
    "ORD-999997": date(2026, 8, 31),
    "ORD-999998": date(2026, 9, 1),
    "ORD-999999": date(2026, 10, 15),
}
TIME_SENSITIVE_TEST_ORDERS = {
    "ORD-999992": date(2026, 7, 25),
    "ORD-999993": date(2026, 8, 30),
    "ORD-999994": date(2026, 9, 2),
    "ORD-999995": date(2026, 10, 25),
}
TIME_SENSITIVE_ORDER_DATES = TIME_SENSITIVE_DEV_ORDERS | TIME_SENSITIVE_TEST_ORDERS


def time_sensitive_fixtures(settings: OrdersSettings) -> tuple[list[Order], list[Shipment]]:
    """Use fixed mock facts independent of the catalog and the random seed."""
    orders: list[Order] = []
    shipments: list[Shipment] = []
    lead = timedelta(days=settings.shipping_lead_days)
    for order_id, order_date in TIME_SENSITIVE_ORDER_DATES.items():
        delivered_at = order_date + 2 * lead
        item = OrderItem(
            item_id=f"{order_id}-ITEM",
            product_id="demo-policy-item",
            model="",
            name="Demo Item",
            category="",
            quantity=1,
            unit_price=Decimal("49.99"),
            final_sale=False,
            refunded_quantity=0,
        )
        orders.append(
            Order(
                order_id=order_id,
                customer_id=TIME_SENSITIVE_CUSTOMER.customer_id,
                status=OrderStatus.DELIVERED,
                order_date=order_date,
                delivered_at=delivered_at,
                currency=settings.currency,
                total=item.unit_price,
                paid_with_coupon=False,
                coupon_code=None,
                items=[item],
            )
        )
        shipments.append(
            Shipment(
                order_id=order_id,
                carrier="Mock Carrier",
                tracking_number=f"MOCK-{order_id}",
                status="delivered",
                shipped_at=order_date + lead,
                expected_delivery=delivered_at,
                last_event_at=datetime.combine(delivered_at, time.min, UTC),
                last_event="Delivered to the mock customer.",
            )
        )
    return orders, shipments
