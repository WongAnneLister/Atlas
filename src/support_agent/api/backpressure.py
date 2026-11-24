"""Bounded in-flight concurrency backpressure and short-TTL demo-customer cache."""

from __future__ import annotations

from collections.abc import Callable
from threading import Lock
from time import monotonic

from support_agent.orders.models import CustomerSummary


class InFlightLimiter:
    """Non-blocking concurrency gate; rejects overflow with 503 + Retry-After."""

    def __init__(self, max_in_flight: int, retry_after_s: int) -> None:
        if max_in_flight <= 0:
            raise ValueError("max_in_flight must be positive")
        self.max_in_flight = max_in_flight
        self.retry_after_s = max(1, retry_after_s)
        self._lock = Lock()
        self._in_flight = 0

    @property
    def in_flight(self) -> int:
        with self._lock:
            return self._in_flight

    def try_acquire(self) -> bool:
        with self._lock:
            if self._in_flight >= self.max_in_flight:
                return False
            self._in_flight += 1
            return True

    def release(self) -> None:
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)


class CustomerAllowlistCache:
    """Short-TTL cache around list_customers so hot /api/chat turns avoid a DB query."""

    def __init__(
        self,
        loader: Callable[[int], list[CustomerSummary]],
        *,
        ttl_s: float = 30.0,
    ) -> None:
        self._loader = loader
        self._ttl_s = max(0.0, ttl_s)
        self._lock = Lock()
        self._expires_at = 0.0
        self._cached_limit: int | None = None
        self._items: list[CustomerSummary] | None = None
        self._ids: frozenset[str] = frozenset()

    def list_customers(self, limit: int) -> list[CustomerSummary]:
        if self._ttl_s <= 0.0:
            return self._loader(limit)
        now = monotonic()
        with self._lock:
            if self._items is not None and self._cached_limit == limit and now < self._expires_at:
                return list(self._items)
        fresh = self._loader(limit)
        with self._lock:
            self._items = list(fresh)
            self._ids = frozenset(c.customer_id for c in fresh)
            self._cached_limit = limit
            self._expires_at = monotonic() + self._ttl_s
        return list(fresh)

    def contains(self, customer_id: str, limit: int) -> bool:
        if self._ttl_s <= 0.0:
            return any(c.customer_id == customer_id for c in self._loader(limit))
        now = monotonic()
        with self._lock:
            if self._items is not None and self._cached_limit == limit and now < self._expires_at:
                return customer_id in self._ids
        self.list_customers(limit)
        with self._lock:
            return customer_id in self._ids
