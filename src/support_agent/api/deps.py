"""Dependencies owned by the chat application."""

from collections.abc import Callable
from dataclasses import dataclass

from support_agent.config import Settings
from support_agent.graph.deps import GraphDeps
from support_agent.orders.service import OrderService


@dataclass
class ApiDeps:
    settings: Settings
    graph_deps: GraphDeps
    order_service: OrderService
    milvus_check: Callable[[], bool]
    warmup: bool = False
