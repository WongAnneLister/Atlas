"""Run the same order contract against both SQL databases."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import SecretStr

from support_agent.config import Settings
from support_agent.db.migrate import upgrade
from support_agent.orders import InvalidRefundRequest, OrderNotFound, RefundAlreadyPending
from support_agent.orders.models import CustomerSummary
from support_agent.orders.seed import generate_dataset, seed_orders
from support_agent.orders.service import OrderService


@pytest.fixture(params=["sqlite", pytest.param("postgresql", marks=pytest.mark.integration)])
def order_repository(request, seeded):
    local, sqlite = seeded
    if request.param == "sqlite":
        yield local, sqlite
        return

    settings, url = request.getfixturevalue("postgres_database")
    settings.orders = local.orders
    settings.data = local.data
    url = url.update_query_dict({"options": "-c timezone=America/Los_Angeles"})
    settings.database_url = SecretStr(url.render_as_string(hide_password=False))
    service = OrderService(platform=settings)
    try:
        upgrade(service.repository.engine)
        seed_orders(settings)
        yield settings, service
    finally:
        service.close()


def test_order_repository_contract(order_repository: tuple[Settings, OrderService]) -> None:
    settings, service = order_repository
    expected = generate_dataset(settings)
    repository = service.repository
    assert repository.seed_metadata() == expected.metadata
    assert service.list_customers(1) == [
        CustomerSummary(
            customer_id=expected.customers[0].customer_id, name=expected.customers[0].name
        )
    ]
    first = expected.orders[0]
    owner = first.customer_id
    assert service.customer_exists(owner)
    assert not service.customer_exists("missing")
    assert service.get_order(first.order_id, owner) == first
    assert isinstance(service.get_order(first.order_id, owner).total, Decimal)
    assert service.list_recent_orders(owner, len(expected.orders)) == sorted(
        (order for order in expected.orders if order.customer_id == owner),
        key=lambda order: (order.order_date, order.order_id),
        reverse=True,
    )
    shipments = {shipment.order_id: shipment for shipment in expected.shipments}
    for order in expected.orders:
        tracking = service.get_tracking(order.order_id, order.customer_id)
        expected_tracking = shipments.get(order.order_id)
        assert tracking == expected_tracking
        if tracking is not None and expected_tracking is not None:
            assert tracking.last_event_at.isoformat() == expected_tracking.last_event_at.isoformat()
    with pytest.raises(OrderNotFound):
        service.get_tracking(first.order_id, "missing")
    with pytest.raises(OrderNotFound):
        service.create_refund_request(first.order_id, "missing", [], "")
    with pytest.raises(InvalidRefundRequest):
        service.create_refund_request(first.order_id, owner, ["missing"], "Issue")
    item = first.items[0].item_id
    with pytest.raises(InvalidRefundRequest):
        service.create_refund_request(first.order_id, owner, [item], " ")
    refund = repository.create_refund_request(
        first.order_id, owner, [item], "Issue", "REF-contract", datetime(2026, 11, 9, tzinfo=UTC)
    )
    assert refund.item_ids == [item]
    assert refund.status == "pending_review"
    assert service.get_order(first.order_id, owner) == first


def test_refund_write_replays_once(order_repository: tuple[Settings, OrderService]) -> None:
    _, service = order_repository
    order = service.list_recent_orders("CUST-0001")[0]
    items = [order.items[0].item_id]
    request = service.create_refund_request(
        order.order_id, order.customer_id, items, "Issue", idempotency_key="refund-turn"
    )
    assert request.request_id.startswith("REF-")
    assert (
        service.create_refund_request(
            order.order_id, order.customer_id, items, "Issue", idempotency_key="refund-turn"
        )
        == request
    )
    with pytest.raises(InvalidRefundRequest):
        service.create_refund_request(
            order.order_id,
            order.customer_id,
            items,
            "Different issue",
            idempotency_key="refund-turn",
        )


def test_repository_returns_one_refund_and_rejects_cross_order_key(order_repository) -> None:
    _, service = order_repository
    first, second = service.list_recent_orders("CUST-0001", limit=2)
    key = "conversation+turn+request"
    args = (first.order_id, first.customer_id, [first.items[0].item_id], "Issue")
    original = service.create_refund_request(*args, idempotency_key=key)
    assert service.create_refund_request(*args, idempotency_key=key) == original
    with pytest.raises(InvalidRefundRequest, match="key was already used"):
        service.create_refund_request(
            second.order_id,
            second.customer_id,
            [second.items[0].item_id],
            "Issue",
            idempotency_key=key,
        )
    with service.repository.connection() as connection:
        assert (
            connection.exec_driver_sql("SELECT idempotency_key FROM refund_requests").scalar_one()
            == key
        )


def test_pending_request_blocks_another_request_for_the_same_item(order_repository) -> None:
    _, service = order_repository
    order = service.get_order("ORD-000004", "CUST-0001")
    first, second = (item.item_id for item in order.items)
    ids = (order.order_id, order.customer_id)
    original = service.create_refund_request(*ids, [first], "Issue", idempotency_key="chat-one")
    with pytest.raises(RefundAlreadyPending):
        service.create_refund_request(*ids, [first], "Changed my mind", idempotency_key="chat-two")
    with pytest.raises(RefundAlreadyPending):
        service.create_refund_request(*ids, [second, first], "Both items")
    # A replay of the same write still returns the original request.
    assert service.create_refund_request(*ids, [first], "Issue", idempotency_key="chat-one") == (
        original
    )
    assert service.pending_refund_item_ids(*ids) == [first]
    # The turn that wrote the request does not see its own write as a conflict.
    assert service.pending_refund_item_ids(*ids, idempotency_key="chat-one") == []
    service.create_refund_request(*ids, [second], "Issue", idempotency_key="chat-three")
    assert service.pending_refund_item_ids(*ids) == [first, second]
    with pytest.raises(OrderNotFound):
        service.pending_refund_item_ids(order.order_id, "missing")
    with service.repository.connection() as connection:
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM refund_requests").scalar_one() == 2


def test_pending_request_without_a_key_still_blocks(order_repository) -> None:
    _, service = order_repository
    order = service.get_order("ORD-000002", "CUST-0001")
    item = [order.items[0].item_id]
    service.repository.create_refund_request(
        order.order_id, order.customer_id, item, "Issue", "REF-unkeyed", datetime.now(UTC)
    )
    with pytest.raises(RefundAlreadyPending):
        service.create_refund_request(
            order.order_id, order.customer_id, item, "Issue", idempotency_key="later-chat"
        )


def test_concurrent_chats_cannot_both_pass_the_pending_check(order_repository) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from sqlalchemy import event

    _, service = order_repository
    order = service.get_order("ORD-000003", "CUST-0001")
    first_read, second_read = Event(), Event()

    def after_query(connection, cursor, statement, parameters, context, executemany) -> None:
        # Hold the first writer right after its pending check until the second one checks.
        if "JOIN refund_requests" not in statement:
            return
        if first_read.is_set():
            second_read.set()
        else:
            first_read.set()
            second_read.wait(0.5)

    event.listen(service.repository.engine, "after_cursor_execute", after_query)

    def request(key: str) -> str:
        ids = (order.order_id, order.customer_id, [order.items[0].item_id], "Issue")
        return service.create_refund_request(*ids, idempotency_key=key).request_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(request, "chat-one")
        assert first_read.wait(2)
        second = pool.submit(request, "chat-two")
        assert first.result(timeout=5).startswith("REF-")
        with pytest.raises(RefundAlreadyPending):
            second.result(timeout=5)
    with service.repository.connection() as connection:
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM refund_requests").scalar_one() == 1
