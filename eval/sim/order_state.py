"""Keep one simulated conversation's order writes out of the next one.

Every simulator eval runs against a scratch copy of the seeded orders database. A refund
request created in one conversation (or left in the source database by an earlier run)
holds its items "in review", so a later conversation about the same order is correctly
handed off instead of approved. The suite therefore refuses to start on a database that
already holds refund requests, and removes the requests each conversation creates.
"""

from __future__ import annotations

from sqlalchemy import delete, select

from support_agent.orders import tables
from support_agent.orders.service import OrderService


def refund_request_ids(order_service: OrderService) -> set[str]:
    with order_service.repository.connection() as connection:
        rows = connection.execute(select(tables.refund_requests.c.request_id)).scalars()
        return set(rows)


def require_no_refund_requests(order_service: OrderService) -> None:
    """Fail before any chat when the scratch database already holds refund requests."""
    found = sorted(refund_request_ids(order_service))
    if found:
        raise ValueError(
            f"orders database already holds {len(found)} refund request(s) "
            f"(first: {found[0]}); start from a freshly seeded copy"
        )


def drop_refund_requests(order_service: OrderService, request_ids: set[str]) -> int:
    """Remove the given refund requests and their items; returns how many were removed."""
    if not request_ids:
        return 0
    requests, items = tables.refund_requests, tables.refund_request_items
    with order_service.repository.connection(write=True) as connection:
        connection.execute(delete(items).where(items.c.request_id.in_(request_ids)))
        result = connection.execute(delete(requests).where(requests.c.request_id.in_(request_ids)))
        return int(result.rowcount or 0)
