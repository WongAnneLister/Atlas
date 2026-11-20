"""Small, prompt-free reliability records and callbacks for live metrics."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from support_agent.llm import Role

ReliabilityOutcome = Literal["success", "error"]


class ReliabilityEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    call_site: str
    dependency: str
    role: Role | None = None
    model: str | None = None
    attempts: int = Field(ge=0)
    retries: int = Field(default=0, ge=0)
    fell_back: bool = False
    fallback_error_type: str | None = None
    repaired: bool = False
    error_type: str | None = None


class ReliabilityObserver(Protocol):
    def llm_attempt(
        self, role: Role, model: str, outcome: ReliabilityOutcome, seconds: float
    ) -> None: ...

    def retry(self, dependency: str) -> None: ...

    def fallback(self, role: Role) -> None: ...

    def repair(self, call_site: str, outcome: ReliabilityOutcome) -> None: ...


_events: ContextVar[list[ReliabilityEvent] | None] = ContextVar("reliability_events", default=None)


@contextmanager
def collect_events() -> Iterator[list[ReliabilityEvent]]:
    events: list[ReliabilityEvent] = []
    token = _events.set(events)
    try:
        yield events
    finally:
        _events.reset(token)


def record_event(event: ReliabilityEvent) -> None:
    events = _events.get()
    if events is not None:
        events.append(event)
