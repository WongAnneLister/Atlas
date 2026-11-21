"""Read-only LangChain tools bound to a trusted customer, never model arguments."""

from typing import Any, Protocol

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from support_agent.graph.model_data import order_data, shipment_data
from support_agent.orders.models import Order, Shipment


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


class OrderReader(Protocol):
    def get_order(self, order_id: str, customer_id: str) -> Order: ...
    def list_recent_orders(self, customer_id: str) -> list[Order]: ...
    def get_tracking(self, order_id: str, customer_id: str) -> Shipment | None: ...


def build_order_tools(service: OrderReader, customer_id: str) -> list[BaseTool]:
    if not customer_id.strip():
        raise ValueError("A trusted customer id is required")

    def get_order(order_id: str) -> dict[str, Any]:
        return order_data(service.get_order(order_id, customer_id))

    def list_recent_orders() -> list[dict[str, Any]]:
        return [order_data(order) for order in service.list_recent_orders(customer_id)]

    def get_tracking(order_id: str) -> dict[str, Any] | None:
        shipment = service.get_tracking(order_id, customer_id)
        return shipment_data(shipment) if shipment else None

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
