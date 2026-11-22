"""Audit the mock database and reproduce its schema/case guide. Run make eval-orders."""

from __future__ import annotations

import subprocess
from collections import Counter
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory

from support_agent.config import REPO_ROOT, get_settings
from support_agent.data.doc_models import digest, json_text, write_text
from support_agent.orders import OrderNotFound, OrderService
from support_agent.orders.fixtures import scenarios
from support_agent.orders.models import OrderStatus
from support_agent.orders.seed import generate_dataset
from support_agent.orders.sql_repository import OrderRepository

TABLES = (
    "customers",
    "orders",
    "order_items",
    "shipments",
    "refund_requests",
    "refund_request_items",
    "seed_metadata",
)


def snapshot(repository: OrderRepository) -> dict[str, list[dict[str, object]]]:
    with repository.connection() as connection:
        return {
            table: [
                dict(row)
                for row in connection.exec_driver_sql(
                    f"SELECT * FROM {table} ORDER BY rowid"  # Identifiers come only from TABLES.
                ).mappings()
            ]
            for table in TABLES
        }


def main() -> None:
    settings = get_settings()
    repository = OrderRepository.from_settings(settings, REPO_ROOT / settings.orders.db_path)
    metadata = repository.seed_metadata()
    service = OrderService(REPO_ROOT / settings.orders.db_path, settings.orders)
    original = snapshot(repository)
    dataset = generate_dataset(settings)
    if dataset != generate_dataset(settings):
        raise ValueError("Seed generation is not deterministic")
    edge_lines: list[str] = []
    for case in scenarios(settings.orders):
        order_id = metadata.edge_cases[case.name]
        order = service.get_order(order_id, dataset.customers[0].customer_id)
        shipment = service.get_tracking(order_id, order.customer_id)
        age = (metadata.today - order.delivered_at).days if order.delivered_at else None
        if order.status != case.status or (
            case.delivery_age is not None and age != case.delivery_age
        ):
            raise ValueError(f"Incorrect edge case: {case.name}")
        if case.final_sale and not any(item.final_sale for item in order.items):
            raise ValueError("Missing final-sale case")
        if case.coupon and not order.paid_with_coupon:
            raise ValueError("Missing coupon case")
        if case.delayed and (
            shipment is None
            or shipment.status != "delayed"
            or (metadata.today - shipment.last_event_at.date()).days
            != settings.orders.tracking_delay_days
        ):
            raise ValueError("Missing delayed-tracking case")
        edge_lines.append(
            f"| {case.name} | {order_id} | {order.customer_id} | {order.status.value} | "
            f"{age if age is not None else '-'} |"
        )
    blocked = 0
    for row in original["orders"]:
        order_id, owner = str(row["order_id"]), str(row["customer_id"])
        stranger = next(
            (c.customer_id for c in dataset.customers if c.customer_id != owner),
            "CUST-NOT-THE-OWNER",
        )
        for operation in (
            partial(service.get_order, order_id, stranger),
            partial(service.get_tracking, order_id, stranger),
            partial(service.create_refund_request, order_id, stranger, [], "Ownership audit"),
        ):
            try:
                operation()
            except OrderNotFound as exc:
                if str(exc) != "Order not found":
                    raise ValueError("Ownership errors leaked existence") from exc
                blocked += 1
            else:
                raise ValueError(f"Ownership check failed for {owner}")
    for customer in dataset.customers:
        if any(
            order.customer_id != customer.customer_id
            for order in service.list_recent_orders(
                customer.customer_id,
                limit=settings.orders.n_orders,
            )
        ):
            raise ValueError("Recent orders leaked across customers")
    with TemporaryDirectory(prefix="support-orders-eval-") as temporary:
        temporary_path = Path(temporary) / "orders.sqlite"
        probe = OrderRepository.from_settings(settings, temporary_path)
        probe.replace(dataset)
        first = snapshot(probe)
        for table in TABLES:
            if (
                table not in {"refund_requests", "refund_request_items"}
                and original[table] != first[table]
            ):
                raise ValueError("Database differs from current seed inputs; run make data-orders")
        temp_service = OrderService(temporary_path, settings.orders)
        chosen = dataset.orders[0]
        before = temp_service.get_order(chosen.order_id, chosen.customer_id)
        request = temp_service.create_refund_request(
            chosen.order_id,
            chosen.customer_id,
            [chosen.items[0].item_id],
            "Audit request",
        )
        if temp_service.get_order(chosen.order_id, chosen.customer_id) != before:
            raise ValueError("Creating a request changed order facts")
        request_rows = len(snapshot(probe)["refund_requests"]) - len(first["refund_requests"])
        if request_rows != 1 or request.status != "pending_review":
            raise ValueError("Request creation did not persist a pending review")
        probe.replace(dataset)
        if snapshot(probe) != first:
            raise ValueError("Reseeding failed to restore the original database")
    if snapshot(repository) != original:
        raise ValueError("Read-only audit modified the configured database")
    sha = subprocess.check_output(
        ["git", "-c", f"safe.directory={REPO_ROOT.as_posix()}", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        text=True,
    ).strip()
    code = sorted((REPO_ROOT / "src/support_agent/orders").glob("*"))
    code_hash = digest(
        "".join(
            p.name + digest(p.read_text(encoding="utf-8"))
            for p in code
            if p.suffix in {".py", ".sql"}
        )
    )
    statuses = Counter(str(row["status"]) for row in original["orders"])
    report = "\n".join(
        [
            "# Mock order seed report",
            "",
            "Generated by `make eval-orders`. Do not edit by hand.",
            "",
            f"- Git SHA (base revision when run): `{sha}`",
            f"- Orders code hash: `{code_hash}`",
            f"- Config hash: `{metadata.config_hash}`",
            f"- Catalog hash: `{metadata.catalog_hash}`",
            f"- Seeded dataset hash: `{digest(json_text(first))}`",
            f"- Run date (UTC): {datetime.now(UTC).date().isoformat()}",
            f"- Fixed today: {metadata.today}; seed: {metadata.seed}",
            f"- Dataset version: mock-orders-v1; catalog source: `{metadata.catalog_source}`",
            "- Model names: none; no LLM, embeddings or reranker used.",
            "- Eval split: not applicable (full synthetic dataset integrity, no tuning).",
            "",
            "## Measured counts",
            "",
            "| Record | Count |",
            "|---|---:|",
            *[
                f"| {table} | {len(original[table])} |"
                for table in TABLES
                if table != "seed_metadata"
            ],
            f"| distinct statuses | {len(statuses)} |",
            f"| named edge cases | {len(edge_lines)} |",
            f"| cross-customer operations blocked | {blocked} |",
            f"| pending-review rows created in isolated probe | {request_rows} |",
            "",
            "| Order status | Count |",
            "|---|---:|",
            *[f"| {status.value} | {statuses[status.value]} |" for status in OrderStatus],
            "",
            "## Integrity checks",
            "",
            "- Repeated generation: identical typed records, ids, amounts and metadata.",
            "- Repeated SQLite reseed: identical sorted rows; prior requests removed.",
            "- Configured database: matches current seed inputs; audit changes no tables.",
            "- Every order: owner enforced for reads, tracking and refund request creation.",
            "- Recent orders: scoped to each customer.",
            "- Refund request: pending review persisted; order and items unchanged.",
            "- Money: integer cents in SQLite, Decimal amounts in service results.",
            "",
            "## Named edge cases",
            "",
            "| Case | Order id | Customer id | Status | Days since delivery |",
            "|---|---|---|---|---:|",
            *edge_lines,
            "",
            "These are synthetic fixtures, not refund eligibility decisions or quality metrics.",
            "",
        ]
    )
    write_text(REPO_ROOT / "eval/reports/orders_seed.md", report)
    guide = """# Mock orders and OrderService

Generated by `make eval-orders`; measured counts and demonstration ids follow below.

## Build and reset

Run `make data-orders` to replace the configured mock database and regenerate this guide.
Reseeding clears all mock orders, tracking and refund requests. Use only the demo database.
Run `make eval-orders` to audit existing seed facts without changing the configured database.
`make data` builds the catalog before seeding orders.
Database location, counts, random seed, fixed today, distributions and date offsets live in
`configs/default.yaml` under `orders`. The SQLite file is gitignored.
Orders use the processed catalog when present, otherwise the configured built-in demo products.
An invalid or empty existing catalog fails explicitly; it never silently switches products.
Catalog ids, names and categories are reused. Every price is synthetic, not a catalog price.
The catalog fingerprint is recorded; changing the catalog changes the seeded dataset.
All named edge cases belong to the first demo customer. Other orders cycle through customers.
Named cases isolate coupon and final-sale flags; random orders use the configured distributions.
Emails use example.com. No real customer data or payment integration is involved.

## Dated policy fixture orders

The seed appends delivered generic-store orders for the fake customer `CUST-TS01`
(`policy.demo@example.com`). These use fixed facts and do not draw from the random seed.
`orders.n_orders` and `orders.n_customers` count the original seeded records.
Each order has a plain demo product with blank model and category fields.
Dev uses the exact policy boundary. Test uses distinct nearby dates.
Each split also includes an earlier order and a later order.

| Split | Order | Placed | Policy version |
|---|---|---|---|
| dev | `ORD-999996` | 2026-08-20 | Historical |
| dev | `ORD-999997` | 2026-08-31 | Historical |
| dev | `ORD-999998` | 2026-09-01 | Current |
| dev | `ORD-999999` | 2026-10-15 | Current |
| test | `ORD-999992` | 2026-07-25 | Historical |
| test | `ORD-999993` | 2026-08-30 | Historical |
| test | `ORD-999994` | 2026-09-02 | Current |
| test | `ORD-999995` | 2026-10-25 | Current |

## Schema

The executable schema is `src/support_agent/orders/schema.sql`.

| Table | Purpose |
|---|---|
| customers | Fake id, display name and example.com email |
| orders | Owner, status, order/delivery dates, currency, charged total and coupon |
| order_items | Product/model, category, quantity, net unit price, final sale, refunded quantity |
| shipments | Mock carrier, tracking number, status, shipping/expected dates and last scan |
| refund_requests | Owner/order, reason, creation time and pending_review status |
| refund_request_items | Selected items; composite foreign keys enforce the same order |
| seed_metadata | Fixed date, seed, config/catalog hashes and named case ids |

SQLite stores money as integer cents; Pydantic models return Decimal values.
Item unit prices already include any coupon discount. Order totals sum these charged amounts.
Historical refunded quantities represent mock facts; seeding does not create pending requests.
All connections enable foreign keys. Reseeding replaces known tables in a transaction.

## Service contract

Import `OrderService` and `OrderNotFound` from `support_agent.orders`.
Callers supply a trusted customer id; this service is not an authentication system.

- `get_order(order_id, customer_id)` returns the owned order and its items.
- `list_recent_orders(customer_id, limit=None)` uses the configured default when omitted.
  Dates sort newest first; order ids break ties. Unknown customers get an empty list.
  Nonpositive limits are rejected rather than becoming an unlimited SQLite query.
- `get_tracking(order_id, customer_id)` returns the owned shipment, or None before shipping.
- `create_refund_request(order_id, customer_id, item_ids, reason)` records pending_review.
  It validates ownership first, then a nonempty, unique subset of that order's item ids.
  It requires a nonblank reason and writes the request/items in a transaction.
  It never changes order status, refunded quantities, totals, shipments, or moves money.

Missing and foreign orders both raise `OrderNotFound("Order not found")`.
Queries bind parameters; no caller text is interpolated into SQL.
Refund requests use fresh ids and the current UTC time; seed facts use the fixed config date.
Policy eligibility belongs to commit 12. LangChain wrappers belong to commit 10.
Request retries can create multiple reviews; idempotency is deferred to the production phase.

## Audit and demonstration orders

"""
    write_text(REPO_ROOT / "docs/ORDERS.md", guide + report)


if __name__ == "__main__":
    main()
