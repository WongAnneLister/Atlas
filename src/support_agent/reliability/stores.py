"""Apply guards at the store and reranker boundaries without changing retrieval scores."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from threading import Lock
from time import monotonic

from support_agent.config import Settings
from support_agent.orders.models import CustomerSummary, Order, RefundRequest, Shipment
from support_agent.orders.service import OrderService
from support_agent.reliability.guards import DependencyGuards
from support_agent.retrieval.filters import RetrievalFilters
from support_agent.retrieval.milvus_store import MilvusStore, SearchHit
from support_agent.retrieval.rerank import Reranker
from support_agent.retrieval.types import RetrievedChunk


class GuardedMilvusSearch:
    def __init__(
        self,
        settings: Settings,
        guards: DependencyGuards,
        *,
        provenance_settings: Settings | None = None,
    ) -> None:
        self._provenance_settings = provenance_settings
        self._settings = settings
        self._guards = guards
        self._store: MilvusStore | None = None
        self._lock = Lock()

    def _client(self, timeout_s: float) -> MilvusStore:
        with self._lock:
            if self._store is None:
                self._store = MilvusStore(
                    self._settings,
                    timeout_s=timeout_s,
                    provenance_settings=self._provenance_settings,
                )
            return self._store

    @contextmanager
    def filter_scope(self) -> Iterator[None]:
        def resolve(seconds: float) -> tuple[MilvusStore, str]:
            store = self._client(seconds)
            return store, store.resolve_read_target(timeout_s=seconds)

        store, target = self._guards.call("milvus", resolve)
        with store.use_read_target(target):
            yield

    def supports_filters(self) -> bool:
        return self._guards.call(
            "milvus", lambda seconds: self._client(seconds).supports_filters(timeout_s=seconds)
        )

    def search_dense(
        self, vector: list[float], limit: int, *, filters: RetrievalFilters | None = None
    ) -> list[SearchHit]:
        return self._guards.call(
            "milvus",
            lambda seconds: self._client(seconds).search_dense(
                vector, limit, timeout_s=seconds, filters=filters
            ),
        )

    def search_bm25(
        self, text: str, limit: int, *, filters: RetrievalFilters | None = None
    ) -> list[SearchHit]:
        return self._guards.call(
            "milvus",
            lambda seconds: self._client(seconds).search_bm25(
                text, limit, timeout_s=seconds, filters=filters
            ),
        )

    def current_build_id(self) -> str | None:
        return self._store.current_build_id() if self._store is not None else None

    def close(self) -> None:
        if self._store is not None:
            self._store.close()


class GuardedReranker:
    def __init__(self, factory: Callable[[], Reranker], guards: DependencyGuards) -> None:
        self._factory = factory
        self._guards = guards
        self._reranker: Reranker | None = None

    def rerank(self, query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        def score(_: float) -> list[RetrievedChunk]:
            if self._reranker is None:
                self._reranker = self._factory()
            return self._reranker.rerank(query, chunks)

        return self._guards.call("reranker", score)


class GuardedOrders:
    def __init__(self, service: Callable[[], OrderService], guards: DependencyGuards) -> None:
        self._service = service
        self._guards = guards

    def list_customers(self, limit: int) -> list[CustomerSummary]:
        return self._guards.call("orders_db", lambda _: self._service().list_customers(limit))

    def customer_email(self, customer_id: str) -> str | None:
        return self._guards.call("orders_db", lambda _: self._service().customer_email(customer_id))

    def customer_exists(self, customer_id: str) -> bool:
        return self._guards.call(
            "orders_db", lambda _: self._service().customer_exists(customer_id)
        )

    def get_order(self, order_id: str, customer_id: str) -> Order:
        return self._guards.call(
            "orders_db", lambda _: self._service().get_order(order_id, customer_id)
        )

    def list_recent_orders(self, customer_id: str) -> list[Order]:
        return self._guards.call(
            "orders_db", lambda _: self._service().list_recent_orders(customer_id)
        )

    def get_tracking(self, order_id: str, customer_id: str) -> Shipment | None:
        return self._guards.call(
            "orders_db", lambda _: self._service().get_tracking(order_id, customer_id)
        )

    def pending_refund_item_ids(
        self,
        order_id: str,
        customer_id: str,
        *,
        idempotency_key: str | None,
        legacy_turn_id: str | None = None,
    ) -> list[str]:
        return self._guards.call(
            "orders_db",
            lambda _: self._service().pending_refund_item_ids(
                order_id,
                customer_id,
                idempotency_key=idempotency_key,
                legacy_turn_id=legacy_turn_id,
            ),
        )

    def create_refund_request(
        self,
        order_id: str,
        customer_id: str,
        item_ids: list[str],
        reason: str,
        *,
        idempotency_key: str | None,
        legacy_turn_id: str | None = None,
    ) -> RefundRequest:
        def write(remaining: float) -> RefundRequest:
            deadline = monotonic() + remaining
            return self._service().create_refund_request(
                order_id,
                customer_id,
                item_ids,
                reason,
                idempotency_key=idempotency_key,
                legacy_turn_id=legacy_turn_id,
                deadline=deadline,
            )

        return self._guards.call("orders_db", write, idempotent=bool(idempotency_key))
