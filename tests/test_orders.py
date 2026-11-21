from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.orders import InvalidRefundRequest, OrderNotFound, OrderService
from support_agent.orders.models import OrderStatus
from support_agent.orders.seed import generate_dataset, seed_orders
from support_agent.orders.sql_repository import OrderRepository


@pytest.fixture
def order_settings(tmp_path: Path) -> Settings:
    settings = get_settings().model_copy(deep=True)
    settings.orders.db_path = str(tmp_path / "orders.sqlite")
    settings.orders.n_orders = 30
    settings.orders.n_customers = 4
    settings.data.processed_dir = str(tmp_path / "processed")
    return settings


@pytest.fixture
def service(order_settings: Settings) -> OrderService:
    seed_orders(order_settings)
    return OrderService(
        settings=order_settings.orders, clock=lambda: datetime(2026, 11, 9, tzinfo=UTC)
    )


def rows(path: str) -> list[str]:
    with sqlite3.connect(path) as connection:
        return list(connection.iterdump())


def test_seed_repeats_exact_records_and_database(order_settings: Settings) -> None:
    first = seed_orders(order_settings)
    original = rows(order_settings.orders.db_path)
    second = seed_orders(order_settings)
    assert first == second
    assert rows(order_settings.orders.db_path) == original
    assert first.metadata.catalog_source == "built_in"
    assert len(first.customers) == order_settings.orders.n_customers
    assert len(first.orders) == order_settings.orders.n_orders
    assert {order.status for order in first.orders} == set(OrderStatus)
    assert all(customer.email.endswith("@example.com") for customer in first.customers)
    assert all(order.order_date <= order_settings.orders.today for order in first.orders)
    assert all(
        order_settings.orders.min_items <= len(order.items) <= order_settings.orders.max_items
        for order in first.orders
    )


def test_named_edge_cases_and_documented_ids_exist(
    service: OrderService, order_settings: Settings
) -> None:
    metadata = service.repository.seed_metadata()
    owner = "CUST-0001"
    for days in order_settings.orders.delivery_ages_days:
        order = service.get_order(metadata.edge_cases[f"delivered_{days}_days"], owner)
        assert order.delivered_at is not None
        assert (order_settings.orders.today - order.delivered_at).days == days
        assert not order.paid_with_coupon and not any(item.final_sale for item in order.items)
    final_sale = service.get_order(metadata.edge_cases["final_sale"], owner)
    assert any(item.final_sale for item in final_sale.items)
    coupon = service.get_order(metadata.edge_cases["coupon"], owner)
    assert coupon.paid_with_coupon and coupon.coupon_code == order_settings.orders.coupon_code
    partial = service.get_order(metadata.edge_cases["partially_refunded"], owner)
    assert partial.status == OrderStatus.PARTIALLY_REFUNDED
    assert (
        0 < sum(i.refunded_quantity for i in partial.items) < sum(i.quantity for i in partial.items)
    )
    assert (
        service.get_order(metadata.edge_cases["cancelled"], owner).status == OrderStatus.CANCELLED
    )
    delayed = service.get_tracking(metadata.edge_cases["delayed_tracking"], owner)
    assert delayed is not None and delayed.status == "delayed"
    assert (order_settings.orders.today - delayed.last_event_at.date()).days == (
        order_settings.orders.tracking_delay_days
    )
    assert (
        delayed.shipped_at
        <= delayed.last_event_at.date()
        < delayed.expected_delivery
        < metadata.today
    )
    documented = re.findall(
        r"\| (ORD-\d+) \| (CUST-\d+) \|", (REPO_ROOT / "docs/ORDERS.md").read_text(encoding="utf-8")
    )
    assert documented
    assert {order_id for order_id, _ in documented} == set(metadata.edge_cases.values())
    for order_id, customer_id in documented:
        assert service.get_order(order_id, customer_id).order_id == order_id


@pytest.mark.parametrize("operation", ["get_order", "get_tracking", "create_refund_request"])
def test_ownership_is_indistinguishable_from_missing(service: OrderService, operation: str) -> None:
    method = getattr(service, operation)
    extra = ([], "") if operation == "create_refund_request" else ()
    messages = []
    for order_id in ("ORD-000001", "MISSING-ORDER", "' OR 1=1 --"):
        with pytest.raises(OrderNotFound) as error:
            method(order_id, "CUST-0002", *extra)
        messages.append(str(error.value))
    assert messages == ["Order not found"] * len(messages)
    with service.repository.connection() as connection:
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM refund_requests").fetchone()[0] == 0


def test_recent_orders_are_scoped_sorted_and_limited(service: OrderService) -> None:
    orders = service.list_recent_orders("CUST-0001", limit=30)
    assert orders == sorted(
        orders, key=lambda order: (order.order_date, order.order_id), reverse=True
    )
    assert all(order.customer_id == "CUST-0001" for order in orders)
    assert service.list_recent_orders("CUST-0001") == orders[: service.settings.recent_limit]
    assert service.list_recent_orders("CUST-0002", limit=1)[0].customer_id == "CUST-0002"
    assert service.list_recent_orders("MISSING") == []
    assert service.list_recent_orders("' OR 1=1 --") == []


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_invalid_recent_limit_is_rejected(service: OrderService, limit: int) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        service.list_recent_orders("CUST-0001", limit)


def test_tracking_is_optional_before_shipping(service: OrderService) -> None:
    cases = service.repository.seed_metadata().edge_cases
    for name in ("pending", "paid", "cancelled"):
        assert service.get_tracking(cases[name], "CUST-0001") is None
    for name in ("shipped", "in_transit", "refunded", "partially_refunded", "delivered_5_days"):
        assert service.get_tracking(cases[name], "CUST-0001") is not None


def test_refund_request_persists_without_changing_any_order_facts(
    service: OrderService,
    order_settings: Settings,
) -> None:
    order = service.get_order("ORD-000001", "CUST-0001")
    tracking = service.get_tracking(order.order_id, order.customer_id)
    request = service.create_refund_request(
        order.order_id,
        order.customer_id,
        [order.items[0].item_id],
        "  Wrong size  ",
    )
    assert request.status == "pending_review" and request.reason == "Wrong size"
    assert request.created_at == datetime(2026, 11, 9, tzinfo=UTC)
    reopened = OrderService(settings=order_settings.orders)
    assert reopened.get_order(order.order_id, order.customer_id) == order
    assert reopened.get_tracking(order.order_id, order.customer_id) == tracking
    with service.repository.connection() as connection:
        row = connection.exec_driver_sql("SELECT * FROM refund_requests").mappings().one()
        assert row["request_id"] == request.request_id
        assert row["status"] == "pending_review"
        selected = (
            connection.exec_driver_sql("SELECT item_id FROM refund_request_items").mappings().all()
        )
        assert [item["item_id"] for item in selected] == request.item_ids
    seed_orders(order_settings)
    with service.repository.connection() as connection:
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM refund_requests").fetchone()[0] == 0


@pytest.mark.parametrize("invalid", ["empty", "duplicate", "unknown", "other_order", "reason"])
def test_invalid_refund_inputs_do_not_write(service: OrderService, invalid: str) -> None:
    order = service.get_order("ORD-000001", "CUST-0001")
    item_ids, reason = [order.items[0].item_id], "Wrong size"
    if invalid == "empty":
        item_ids = []
    elif invalid == "duplicate":
        item_ids *= 2
    elif invalid == "unknown":
        item_ids = ["MISSING-ITEM"]
    elif invalid == "other_order":
        item_ids = [service.get_order("ORD-000002", "CUST-0001").items[0].item_id]
    else:
        reason = "   "
    with pytest.raises(InvalidRefundRequest):
        service.create_refund_request(order.order_id, order.customer_id, item_ids, reason)
    with service.repository.connection() as connection:
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM refund_requests").fetchone()[0] == 0
        assert (
            connection.exec_driver_sql("SELECT COUNT(*) FROM refund_request_items").fetchone()[0]
            == 0
        )


def test_catalog_products_are_used_and_missing_catalog_has_fallback(
    order_settings: Settings, tmp_path: Path
) -> None:
    catalog = tmp_path / "products.jsonl"
    catalog.write_text(
        '{"product_id":"fixture","model":"BHD999/10","name":"Fixture hair dryer"}\n',
        encoding="utf-8",
    )
    dataset = generate_dataset(order_settings, catalog)
    assert dataset.metadata.catalog_source == "processed_catalog"
    assert all(
        item.product_id == "fixture" and item.category == "hair_dryers"
        for order in dataset.orders
        for item in order.items
    )
    catalog.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="Catalog"):
        generate_dataset(order_settings, catalog)


def test_money_roundtrips_as_decimal_and_integer_cents(service: OrderService) -> None:
    for order in service.list_recent_orders("CUST-0001", limit=30):
        assert isinstance(order.total, Decimal)
        assert order.total == sum((i.unit_price * i.quantity for i in order.items), Decimal(0))
    with service.repository.connection() as connection:
        assert {
            row[0] for row in connection.exec_driver_sql("SELECT typeof(total_cents) FROM orders")
        } == {"integer"}
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []


def test_missing_database_is_not_silently_created(tmp_path: Path) -> None:
    path = tmp_path / "missing.sqlite"
    with pytest.raises(FileNotFoundError, match="make data-orders"):
        OrderRepository.from_settings(get_settings(), path).get_order("ORD-000001", "CUST-0001")
    assert not path.exists()


def test_seed_rejects_too_few_orders_before_reset(order_settings: Settings) -> None:
    seed_orders(order_settings)
    before = rows(order_settings.orders.db_path)
    order_settings.orders.n_orders = 1
    with pytest.raises(ValueError, match="cover all edge cases"):
        seed_orders(order_settings)
    assert rows(order_settings.orders.db_path) == before


def test_failed_reset_rolls_back_existing_tables(order_settings: Settings) -> None:
    dataset = seed_orders(order_settings)
    before = rows(order_settings.orders.db_path)
    invalid = dataset.model_copy(update={"customers": []})
    with pytest.raises(IntegrityError):
        OrderRepository.from_settings(order_settings).replace(invalid)
    assert rows(order_settings.orders.db_path) == before


def test_refund_item_write_failure_rolls_back_request(service: OrderService) -> None:
    order = service.get_order("ORD-000001", "CUST-0001")
    with service.repository.connection() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER reject_request_item BEFORE INSERT ON refund_request_items "
            "BEGIN SELECT RAISE(ABORT, 'fixture failure'); END"
        )
    with pytest.raises(IntegrityError, match="fixture failure"):
        service.create_refund_request(
            order.order_id, order.customer_id, [order.items[0].item_id], "Test rollback"
        )
    with service.repository.connection() as connection:
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM refund_requests").fetchone()[0] == 0
        assert (
            connection.exec_driver_sql("SELECT COUNT(*) FROM refund_request_items").fetchone()[0]
            == 0
        )
    assert service.get_order(order.order_id, order.customer_id) == order


def test_simultaneous_requests_for_one_item_commit_once(service: OrderService) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from sqlalchemy import event

    from support_agent.orders import RefundAlreadyPending

    order = service.get_order("ORD-000001", "CUST-0001")
    first_read, second_read = Event(), Event()

    def after_query(connection, cursor, statement, parameters, context, executemany) -> None:
        if "FROM order_items" not in statement:
            return
        if first_read.is_set():
            second_read.set()
        else:
            first_read.set()
            second_read.wait(0.25)

    event.listen(service.repository.engine, "after_cursor_execute", after_query)

    def request(reason: str) -> str:
        return service.create_refund_request(
            order.order_id, order.customer_id, [order.items[0].item_id], reason
        ).request_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(request, "First issue")
        assert first_read.wait(2)
        second = pool.submit(request, "Second issue")
        assert first.result(timeout=3).startswith("REF-")
        with pytest.raises(RefundAlreadyPending):
            second.result(timeout=3)
    with service.repository.connection() as connection:
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM refund_requests").scalar_one() == 1
