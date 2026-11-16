"""Order facts and request records. These models do not decide refund eligibility."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Money = Annotated[Decimal, Field(ge=0, decimal_places=2)]


class OrderNotFound(LookupError):
    """The order is missing or does not belong to the supplied customer."""


class InvalidRefundRequest(ValueError):
    """The request has invalid item ids or an empty reason."""


class OrderStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    SHIPPED = "shipped"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"


class CustomerSummary(BaseModel):
    customer_id: str
    name: str


class Customer(CustomerSummary):
    email: str = Field(pattern=r"^[^@\s]+@example\.com$")


class OrderItem(BaseModel):
    item_id: str
    product_id: str
    model: str
    name: str
    category: str
    quantity: int = Field(gt=0)
    unit_price: Money  # Net unit price after any coupon discount.
    final_sale: bool
    refunded_quantity: int = Field(ge=0)

    @model_validator(mode="after")
    def _valid_refunded_quantity(self) -> OrderItem:
        if self.refunded_quantity > self.quantity:
            raise ValueError("refunded_quantity exceeds purchased quantity")
        return self


class Order(BaseModel):
    order_id: str
    customer_id: str
    status: OrderStatus
    order_date: date
    delivered_at: date | None
    currency: str
    total: Money
    paid_with_coupon: bool
    coupon_code: str | None
    items: list[OrderItem] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent_facts(self) -> Order:
        if self.total != sum((i.unit_price * i.quantity for i in self.items), Decimal(0)):
            raise ValueError("total differs from charged item prices")
        if self.paid_with_coupon != bool(self.coupon_code):
            raise ValueError("coupon flag and code disagree")
        if len({item.item_id for item in self.items}) != len(self.items):
            raise ValueError("duplicate order item ids")
        delivered = self.status in {
            OrderStatus.DELIVERED,
            OrderStatus.REFUNDED,
            OrderStatus.PARTIALLY_REFUNDED,
        }
        if delivered != (self.delivered_at is not None):
            raise ValueError("delivery date disagrees with order status")
        if self.delivered_at is not None and self.delivered_at < self.order_date:
            raise ValueError("delivery predates order")
        refunded = sum(item.refunded_quantity for item in self.items)
        quantity = sum(item.quantity for item in self.items)
        if self.status == OrderStatus.REFUNDED and refunded != quantity:
            raise ValueError("refunded order needs all quantities refunded")
        if self.status == OrderStatus.PARTIALLY_REFUNDED and not 0 < refunded < quantity:
            raise ValueError("partially refunded order needs a partial quantity")
        if self.status not in {OrderStatus.REFUNDED, OrderStatus.PARTIALLY_REFUNDED} and refunded:
            raise ValueError("unexpected refunded quantities")
        return self


class Shipment(BaseModel):
    order_id: str
    carrier: str
    tracking_number: str
    status: Literal["shipped", "in_transit", "delayed", "delivered"]
    shipped_at: date
    expected_delivery: date
    last_event_at: datetime
    last_event: str


class RefundRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    request_id: str
    order_id: str
    customer_id: str
    item_ids: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1)
    status: Literal["pending_review"]
    created_at: datetime


class SeedMetadata(BaseModel):
    seed: int
    today: date
    catalog_source: str
    catalog_hash: str
    config_hash: str
    edge_cases: dict[str, str]


class SeedDataset(BaseModel):
    customers: list[Customer]
    orders: list[Order]
    shipments: list[Shipment]
    metadata: SeedMetadata
