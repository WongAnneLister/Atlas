"""Run the same order contract against both SQL databases."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import SecretStr

from support_agent.config import Settings
from support_agent.db.migrate import upgrade
from support_agent.orders import InvalidRefundRequest, OrderNotFound
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
