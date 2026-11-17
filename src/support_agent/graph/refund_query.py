"""The policy search query for the refund path, built only from verified order facts.

The original query joined the intent label, item categories and order status. It reads
nothing like the policy text, so the reranker scored it low and the gate handed off
every refund. The "store_faq" mode asks one question in the store FAQ's own words,
names the store that sells the mock orders, and picks the question from the order facts.
Customer text never enters the query.
"""

from __future__ import annotations

from functools import cache
from typing import Any

import yaml

from support_agent.config import Settings
from support_agent.graph.handoff import PROMPTS
from support_agent.orders.models import Order, OrderStatus
from support_agent.retrieval.scope import requested_stores

NOT_SHIPPED = {OrderStatus.PENDING, OrderStatus.PAID}
IN_TRANSIT = {OrderStatus.SHIPPED, OrderStatus.IN_TRANSIT}
TEMPLATE_KEYS = ("final_sale", "coupon", "not_shipped", "in_transit", "default")


@cache
def templates() -> dict[str, str]:
    raw: Any = yaml.safe_load((PROMPTS / "refund_policy_queries.yaml").read_text("utf-8"))
    if not isinstance(raw, dict) or set(raw) != set(TEMPLATE_KEYS):
        raise ValueError(f"refund_policy_queries.yaml needs exactly {TEMPLATE_KEYS}")
    return {str(key): str(value) for key, value in raw.items()}


def template_key(order: Order) -> str:
    """Pick the one policy question that matters most for this order."""
    if any(item.final_sale for item in order.items):
        return "final_sale"
    if order.paid_with_coupon:
        return "coupon"
    if order.status in NOT_SHIPPED:
        return "not_shipped"
    if order.status in IN_TRANSIT:
        return "in_transit"
    return "default"


def order_fields_query(order: Order, intent: str | None) -> str:
    """The original query, kept so the evaluation can compare against it."""
    flags = [item.category for item in order.items]
    if any(item.final_sale for item in order.items):
        flags.append("final sale items")
    if order.paid_with_coupon:
        flags.append("coupon refunds")
    subject = ", ".join(sorted(set(flags)))
    return f"{intent or 'refund'} policy for {subject}; order status {order.status.value}"


def store_faq_query(order: Order, settings: Settings) -> str:
    refund = settings.refund
    query = templates()[template_key(order)].format(store=refund.store_label)
    stores = requested_stores(query, settings.retrieval.store_scope)
    if stores != {refund.policy_store}:
        raise ValueError(
            f"refund.store_label {refund.store_label!r} must name exactly store "
            f"{refund.policy_store!r}; the query names {sorted(stores)}"
        )
    return query


def policy_query(order: Order, intent: str | None, settings: Settings) -> str:
    if settings.refund.policy_query == "store_faq":
        return store_faq_query(order, settings)
    return order_fields_query(order, intent)
