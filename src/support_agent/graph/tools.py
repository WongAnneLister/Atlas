"""Read-only LangChain tools bound to a trusted customer, never model arguments."""

from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from support_agent.orders.service import OrderService


class OrderArgs(BaseModel):
    # Extra customer_id arguments are discarded; only the trusted closure is used.
    model_config = ConfigDict(extra="ignore", strict=True)
    order_id: str = Field(min_length=1)


class RecentArgs(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ToolResult(BaseModel):
    ok: bool
    data: dict[str, Any] | list[dict[str, Any]] | None = None
    error: str | None = None


def build_order_tools(service: OrderService, customer_id: str) -> list[BaseTool]:
    if not customer_id.strip():
        raise ValueError("A trusted customer id is required")

    def get_order(order_id: str) -> dict[str, Any]:
        return service.get_order(order_id, customer_id).model_dump(mode="json")

    def list_recent_orders() -> list[dict[str, Any]]:
        return [order.model_dump(mode="json") for order in service.list_recent_orders(customer_id)]

    def get_tracking(order_id: str) -> dict[str, Any] | None:
        shipment = service.get_tracking(order_id, customer_id)
        return shipment.model_dump(mode="json") if shipment else None

    return [
        StructuredTool.from_function(
            get_order,
            name="get_order",
            description="Read an order belonging to the current customer, using its exact id.",
            args_schema=OrderArgs,
        ),
        StructuredTool.from_function(
            list_recent_orders,
            name="list_recent_orders",
            description="List the current customer's recent orders so they can pick an order.",
            args_schema=RecentArgs,
        ),
        StructuredTool.from_function(
            get_tracking,
            name="get_tracking",
            description="Read shipment tracking for the current customer's exact order id.",
            args_schema=OrderArgs,
        ),
    ]
