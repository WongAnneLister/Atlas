"""Render order-path replies from tool data, so the reply cannot state unread facts.

The order model only chooses lookups and says whether the order data answers the
question. Every sentence below is a fixed template filled with tool values.
See eval/reports/order_replies.md.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from support_agent.graph.handoff import load_templates

REPLY_TOOL = "reply"


class ReplyDecision(BaseModel):
    answer_from_order_data: bool = Field(
        description=(
            "true only if the order and tracking data you read answers the customer's"
            " question; false for store rules, policies, how-to steps or anything else"
            " that is not in that data"
        )
    )


def reply_tool() -> BaseTool:
    """A terminal tool: the loop reads its arguments and never runs it."""

    def reply(answer_from_order_data: bool) -> str:
        raise RuntimeError("The reply tool is handled by the order loop")

    return StructuredTool.from_function(
        reply,
        name=REPLY_TOOL,
        description=(
            "Finish the order lookup. The server writes the reply to the customer from"
            " the order data you read; you never write it."
        ),
        args_schema=ReplyDecision,
    )


Lookup = tuple[str, str | None, Any]  # tool name, order id argument, result data


def _label(value: Any) -> str:
    """Status codes read as words: in_transit -> in transit."""
    return str(value).replace("_", " ")


def _order(data: dict[str, Any], t: dict[str, str]) -> list[str]:
    lines = [t["order"].format(**{**data, "status": _label(data["status"])})]
    if data.get("delivered_at"):
        lines.append(t["delivered"].format(**data))
    if data.get("coupon_code"):
        lines.append(t["coupon"].format(**data))
    lines.append(t["items_header"])
    for item in data.get("items", []):
        line = t["item"].format(**item, currency=data["currency"])
        if item.get("refunded_quantity"):
            line += t["item_refunded"].format(**item)
        if item.get("final_sale"):
            line += t["item_final_sale"]
        lines.append(line)
    return lines


def _tracking(order_id: str | None, data: dict[str, Any] | None, t: dict[str, str]) -> list[str]:
    if not data:
        return [t["no_tracking"].format(order_id=order_id or "this order")]
    values = {**data, "status": _label(data["status"])}
    last_date = str(data.get("last_event_at", ""))[:10]
    return [
        t["tracking"].format(**values),
        t["tracking_estimate"].format(**values),
        t["tracking_last_event"].format(**values, last_event_date=last_date),
    ]


def _recent(data: list[dict[str, Any]], t: dict[str, str], pick: bool) -> list[str]:
    lines = [t["recent_header"]]
    lines += [t["recent_item"].format(**{**o, "status": _label(o["status"])}) for o in data]
    return [*lines, t["recent_pick"]] if pick else lines


def render_order_reply(lookups: list[Lookup], templates: dict[str, str] | None = None) -> str:
    """One block per distinct successful lookup, in call order; repeats are dropped."""
    t = templates or load_templates("order_replies.yaml")
    only_list = all(name == "list_recent_orders" for name, _, _ in lookups)
    blocks: list[list[str]] = []
    seen: set[tuple[str, str | None]] = set()
    for name, order_id, data in lookups:
        if (name, order_id) in seen:
            continue
        seen.add((name, order_id))
        if name == "get_order":
            blocks.append(_order(data, t))
        elif name == "get_tracking":
            blocks.append(_tracking(order_id, data, t))
        elif name == "list_recent_orders":
            blocks.append(_recent(data, t, pick=only_list))
    return "\n\n".join("\n".join(block) for block in blocks)
