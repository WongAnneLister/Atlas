"""Dependencies owned by the chat application."""

from collections.abc import Callable
from dataclasses import dataclass

from prometheus_client import CollectorRegistry

from support_agent.api.readiness import ReadinessChecks
from support_agent.config import Settings
from support_agent.graph.deps import GraphDeps
from support_agent.infra.redis import KeyValueStore
from support_agent.orders.service import OrderService


@dataclass
class ApiDeps:
    settings: Settings
    graph_deps: GraphDeps
    order_service: OrderService
    milvus_check: Callable[[], bool]
    warmup: bool = False
    readiness: ReadinessChecks | None = None
    lock_store: KeyValueStore | None = None
    metrics_registry: CollectorRegistry | None = None
