"""Serialize only the fields intended for the model and delimit untrusted text."""

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel

from support_agent.orders.models import Order, OrderItem, Shipment
from support_agent.retrieval.types import RetrievedChunk

_ORDER_FIELDS = {
    "order_id",
    "customer_id",
    "status",
    "order_date",
    "delivered_at",
    "currency",
    "total",
    "paid_with_coupon",
    "coupon_code",
}
_ITEM_FIELDS = {
    "item_id",
    "product_id",
    "model",
    "name",
    "category",
    "quantity",
    "unit_price",
    "final_sale",
    "refunded_quantity",
}
_SHIPMENT_FIELDS = {
    "order_id",
    "carrier",
    "tracking_number",
    "status",
    "shipped_at",
    "expected_delivery",
    "last_event_at",
    "last_event",
}
_REFUND_FIELDS = {"days_since_order", "days_since_delivery", "today", "pending_refund_item_ids"}


def _fields(value: BaseModel | Mapping[str, Any], names: set[str]) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", include=names)
    return {name: value[name] for name in names if name in value}


def order_data(order: Order | Mapping[str, Any]) -> dict[str, Any]:
    data = _fields(order, _ORDER_FIELDS)
    items = order.items if isinstance(order, Order) else order.get("items")
    if isinstance(items, list):
        data["items"] = [
            _fields(item, _ITEM_FIELDS) for item in items if isinstance(item, (OrderItem, Mapping))
        ]
    return data


def shipment_data(shipment: Shipment | Mapping[str, Any]) -> dict[str, Any]:
    return _fields(shipment, _SHIPMENT_FIELDS)


def lookup_data(context: Mapping[str, Any]) -> dict[str, Any]:
    """Accept the current and saved tool result shapes and discard unknown fields."""
    data: dict[str, Any] = {}
    if isinstance(order := context.get("get_order"), Mapping):
        data["get_order"] = order_data(order)
    if "get_tracking" in context:
        shipment = context["get_tracking"]
        data["get_tracking"] = shipment_data(shipment) if isinstance(shipment, Mapping) else None
    if isinstance(recent := context.get("list_recent_orders"), list):
        data["list_recent_orders"] = [
            order_data(order) for order in recent if isinstance(order, Mapping)
        ]
    return data


def refund_data(context: Mapping[str, Any]) -> dict[str, Any]:
    data = _fields(context, _REFUND_FIELDS)
    if isinstance(order := context.get("order"), Mapping):
        data["order"] = order_data(order)
    return data


def _escape(text: str) -> str:
    # No '<' can start an embedded opening or closing tag. Other policy text stays literal.
    return text.replace("<", "&lt;")


def order_block(text: str) -> str:
    return f"<order_data>\n{_escape(text)}\n</order_data>"


def source_blocks(chunks: Sequence[RetrievedChunk], *, include_validity: bool = False) -> str:
    def validity(chunk: RetrievedChunk) -> str:
        if not include_validity or chunk.effective_from is None:
            return ""
        end = f" until {chunk.effective_to} (end excluded)" if chunk.effective_to else ""
        return f"Validity from {chunk.effective_from}{end}.\n"

    return "\n\n".join(
        f'<source n="{number}">\n[{number}] {_escape(chunk.heading_path)}\n'
        f"{validity(chunk)}{_escape(chunk.text)}\n</source>"
        for number, chunk in enumerate(chunks, start=1)
    )
