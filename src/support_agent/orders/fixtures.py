"""Catalog inputs and named demonstration cases for the deterministic order seed."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from support_agent.config import OrdersSettings, SeedProduct, Settings
from support_agent.orders.models import OrderStatus


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
