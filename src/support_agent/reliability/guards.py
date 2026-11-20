"""Bounded dependency calls for the synchronous graph."""

import sqlite3
from collections.abc import Callable
from time import monotonic
from typing import Literal, TypeVar

from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeout

from support_agent.config import Settings
from support_agent.reliability.circuit import CircuitRegistry
from support_agent.reliability.errors import is_retryable
from support_agent.reliability.events import ReliabilityEvent, ReliabilityObserver, record_event
from support_agent.reliability.retry import retry_call
from support_agent.reliability.timeouts import BoundedExecutor
from support_agent.retrieval.milvus_store import milvus_transport_failure

Dependency = Literal["milvus", "reranker", "orders_db"]
T = TypeVar("T")


class DependencyUnavailable(ConnectionError):
    def __init__(self, dependency: Dependency, error: Exception) -> None:
        super().__init__(f"{dependency} unavailable")
        self.error_type = type(error).__name__


def diagnostic_type(error: Exception) -> str:
    return error.error_type if isinstance(error, DependencyUnavailable) else type(error).__name__


def is_dependency_failure(error: Exception) -> bool:
    return isinstance(error, DependencyUnavailable) or is_retryable(error)


def _transport_error(name: Dependency, error: Exception) -> bool:
    if name == "orders_db":
        if isinstance(error, FileNotFoundError | PoolTimeout):
            return True
        if isinstance(error, DBAPIError):
            original = error.orig
            if error.connection_invalidated:
                return True
            if isinstance(original, sqlite3.OperationalError):
                code = getattr(original, "sqlite_errorcode", 0)
                return code & 0xFF in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_CANTOPEN}
            if type(original).__module__.startswith("psycopg"):
                code = getattr(original, "sqlstate", None)
                return (
                    code is None
                    and type(original).__name__ in {"OperationalError", "InterfaceError"}
                ) or bool(code and (code.startswith("08") or code in {"57014", "57P01", "57P03"}))
    return name == "milvus" and milvus_transport_failure(error)


class DependencyGuards:
    def __init__(
        self,
        settings: Settings,
        circuits: CircuitRegistry,
        observer: ReliabilityObserver | None = None,
        fault: Callable[[Dependency], None] | None = None,
    ) -> None:
        self._retry = settings.reliability.retry
        self._circuits = circuits
        self._observer = observer
        self._fault = fault
        self._timeouts: dict[Dependency, float] = {
            "milvus": settings.milvus.timeout_s,
            "reranker": settings.reliability.timeouts_s.rerank,
            "orders_db": settings.reliability.timeouts_s.orders_db,
        }
        self._workers = {
            name: BoundedExecutor(
                max_workers=1 if name == "reranker" else settings.db.pool_size,
                thread_name_prefix=f"atlas-{name}",
            )
            for name in self._timeouts
        }

    def call(
        self, name: Dependency, operation: Callable[[float], T], *, idempotent: bool = True
    ) -> T:
        attempts = retries = 0
        error_type = None

        def perform(remaining: float) -> T:
            nonlocal attempts
            attempts += 1

            def invoke() -> T:
                if self._fault:
                    self._fault(name)
                timeout = min(remaining, self._timeouts[name])
                deadline = monotonic() + timeout

                def run() -> T:
                    seconds = deadline - monotonic()
                    if seconds <= 0:
                        raise TimeoutError("Dependency deadline expired before work could start")
                    return operation(seconds)

                try:
                    return self._workers[name].run(run, timeout)
                except Exception as error:
                    if _transport_error(name, error):
                        raise DependencyUnavailable(name, error) from error
                    raise

            return invoke()

        def on_retry() -> None:
            nonlocal retries
            retries += 1
            if self._observer:
                self._observer.retry(name)

        try:
            # The breaker sees whole calls: one call whose retries all fail counts once.
            if idempotent:
                return self._circuits.call(
                    name,
                    lambda: retry_call(
                        perform, policy=self._retry, is_idempotent=True, on_retry=on_retry
                    ),
                )
            return self._circuits.call(name, lambda: perform(self._retry.budget_s))
        except Exception as error:
            error_type = diagnostic_type(error)
            raise
        finally:
            record_event(
                ReliabilityEvent(
                    call_site=name,
                    dependency=name,
                    attempts=attempts,
                    retries=retries,
                    error_type=error_type,
                )
            )

    def close(self) -> None:
        for executor in self._workers.values():
            executor.close()
