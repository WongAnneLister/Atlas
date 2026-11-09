"""Generate mock order facts from a fixed seed and date. Run make data-orders."""

from __future__ import annotations

import logging
import random
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from support_agent.config import REPO_ROOT, OrdersSettings, SeedProduct, Settings, get_settings
from support_agent.data.doc_models import digest, json_text
from support_agent.orders.db import OrderRepository
from support_agent.orders.fixtures import Scenario, load_products, scenarios
from support_agent.orders.models import (
    Customer,
    Order,
    OrderItem,
    OrderStatus,
    SeedDataset,
    SeedMetadata,
    Shipment,
)

log = logging.getLogger(__name__)


def _dates(
    case: Scenario,
    config: OrdersSettings,
    rng: random.Random,
    number: int,
) -> tuple[date, date | None, Shipment | None]:
    lead = timedelta(days=config.shipping_lead_days)
    delivered = None
    if case.status in {OrderStatus.DELIVERED, OrderStatus.REFUNDED, OrderStatus.PARTIALLY_REFUNDED}:
        age = (
            case.delivery_age
            if case.delivery_age is not None
            else rng.choice(config.delivery_ages_days)
        )
        delivered = config.today - timedelta(days=age)
        shipped = delivered - lead
        expected = delivered
        event = delivered
        status, message = "delivered", "Delivered to the mock customer."
    elif case.status in {OrderStatus.SHIPPED, OrderStatus.IN_TRANSIT}:
        if case.delayed:
            event = config.today - timedelta(days=config.tracking_delay_days)
            shipped = event - lead
            expected = config.today - lead
            status, message = "delayed", "Mock tracking is delayed; no newer scan is available."
        else:
            shipped = (
                config.today
                if case.status == OrderStatus.SHIPPED
                else (config.today - timedelta(days=config.transit_age_days))
            )
            expected, event = config.today + lead, config.today
            status = "shipped" if case.status == OrderStatus.SHIPPED else "in_transit"
            message = "Shipment accepted by the mock carrier."
    else:
        return config.today - timedelta(days=rng.randint(0, config.max_order_age_days)), None, None
    shipment = Shipment(
        order_id=f"ORD-{number:06d}",
        carrier="Mock Carrier",
        tracking_number=f"MOCK-{number:06d}",
        status=status,
        shipped_at=shipped,
        expected_delivery=expected,
        last_event_at=datetime.combine(event, time.min, UTC),
        last_event=message,
    )
    return shipped - lead, delivered, shipment


def _items(
    number: int,
    case: Scenario,
    coupon: bool,
    products: list[SeedProduct],
    prices: dict[str, Decimal],
    config: OrdersSettings,
    rng: random.Random,
    random_flags: bool,
) -> list[OrderItem]:
    count = rng.randint(config.min_items, config.max_items)
    if case.status == OrderStatus.PARTIALLY_REFUNDED and config.max_quantity == 1:
        count = max(count, 2)
    items: list[OrderItem] = []
    for index in range(count):
        product = rng.choice(products)
        quantity = rng.randint(1, config.max_quantity)
        if case.status == OrderStatus.PARTIALLY_REFUNDED and index == 0 and config.max_quantity > 1:
            quantity = max(quantity, 2)
        price = prices[product.product_id]
        if coupon:
            price = (price * (1 - config.coupon_discount)).quantize(Decimal("0.01"))
        refunded = (
            quantity
            if case.status == OrderStatus.REFUNDED
            else int(case.status == OrderStatus.PARTIALLY_REFUNDED and index == 0)
        )
        items.append(
            OrderItem(
                item_id=f"ITEM-{number:06d}-{index + 1:02d}",
                product_id=product.product_id,
                model=product.model,
                name=product.name,
                category=product.category,
                quantity=quantity,
                unit_price=price,
                final_sale=case.final_sale
                or (random_flags and rng.random() < config.final_sale_probability),
                refunded_quantity=refunded,
            )
        )
    return items


def generate_dataset(settings: Settings, catalog_path: Path | None = None) -> SeedDataset:
    config = settings.orders
    cases = scenarios(config)
    if config.n_orders < len(cases):
        raise ValueError(f"orders.n_orders must be at least {len(cases)} to cover all edge cases")
    if config.max_items * config.max_quantity < 2:
        raise ValueError("Seed needs room for a partial refund with an unrefunded quantity")
    path = catalog_path or REPO_ROOT / settings.data.processed_dir / "catalog/products.jsonl"
    products, source = load_products(settings, path)
    rng = random.Random(config.seed)
    prices = {
        p.product_id: Decimal(
            rng.randint(
                config.min_unit_price_cents,
                config.max_unit_price_cents,
            )
        )
        / 100
        for p in products
    }
    customers = [
        Customer(
            customer_id=f"CUST-{i:04d}",
            name=f"Demo Customer {i:04d}",
            email=f"customer{i:04d}@example.com",
        )
        for i in range(1, config.n_customers + 1)
    ]
    orders: list[Order] = []
    shipments: list[Shipment] = []
    edge_cases: dict[str, str] = {}
    for index in range(config.n_orders):
        number = index + 1
        fixed = index < len(cases)
        case = (
            cases[index] if fixed else Scenario(name="random", status=rng.choice(list(OrderStatus)))
        )
        customer = customers[0] if fixed else customers[(index - len(cases)) % len(customers)]
        coupon = case.coupon if fixed else rng.random() < config.coupon_probability
        items = _items(number, case, coupon, products, prices, config, rng, random_flags=not fixed)
        order_date, delivered_at, shipment = _dates(case, config, rng, number)
        order_id = f"ORD-{number:06d}"
        order = Order(
            order_id=order_id,
            customer_id=customer.customer_id,
            status=case.status,
            order_date=order_date,
            delivered_at=delivered_at,
            currency=config.currency,
            total=sum((i.unit_price * i.quantity for i in items), Decimal(0)),
            paid_with_coupon=coupon,
            coupon_code=config.coupon_code if coupon else None,
            items=items,
        )
        orders.append(order)
        if shipment:
            shipments.append(shipment)
        if fixed:
            edge_cases[case.name] = order_id
    return SeedDataset(
        customers=customers,
        orders=orders,
        shipments=shipments,
        metadata=SeedMetadata(
            seed=config.seed,
            today=config.today,
            catalog_source=source,
            catalog_hash=digest(json_text([p.model_dump() for p in products])),
            config_hash=digest(json_text(settings.model_dump(mode="json"))),
            edge_cases=edge_cases,
        ),
    )


def seed_orders(settings: Settings, catalog_path: Path | None = None) -> SeedDataset:
    dataset = generate_dataset(settings, catalog_path)
    repository = OrderRepository(REPO_ROOT / settings.orders.db_path)
    repository.replace(dataset)
    log.info(
        "seeded %d customers, %d orders from %s at fixed date %s",
        len(dataset.customers),
        len(dataset.orders),
        dataset.metadata.catalog_source,
        dataset.metadata.today,
    )
    return dataset


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        seed_orders(get_settings())
    except (OSError, ValueError) as exc:
        log.error("order seed failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
