"""Low-cardinality cache events and per-turn collection for metrics and evals."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

CacheLayer = Literal["embedding", "retrieval", "answer", "answer_semantic"]
CacheOutcome = Literal["hit", "miss", "bypass", "error"]


class CacheEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    layer: CacheLayer
    outcome: CacheOutcome
    reason: str | None = None


class CacheObserver(Protocol):
    def cache_event(self, layer: CacheLayer, outcome: CacheOutcome) -> None: ...


_cache_events: ContextVar[list[CacheEvent] | None] = ContextVar("cache_events", default=None)


@contextmanager
def collect_cache_events() -> Iterator[list[CacheEvent]]:
    events: list[CacheEvent] = []
    token = _cache_events.set(events)
    try:
        yield events
    finally:
        _cache_events.reset(token)


def record_cache_event(
    layer: CacheLayer,
    outcome: CacheOutcome,
    *,
    observer: object | None = None,
    reason: str | None = None,
) -> None:
    events = _cache_events.get()
    if events is not None:
        events.append(CacheEvent(layer=layer, outcome=outcome, reason=reason))
    callback = getattr(observer, "cache_event", None)
    if callable(callback):
        callback(layer, outcome)
