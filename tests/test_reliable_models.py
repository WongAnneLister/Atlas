"""Offline model retries, fallback attribution and configured deadlines."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import Field

from support_agent.config import Settings
from support_agent.graph.build import build_graph
from support_agent.graph.deps import GraphDeps
from support_agent.graph.intents import Intent
from test_graph import StructuredFake, invoke


class TextModel(FakeListChatModel):
    replies: list[str | Exception] = Field(default_factory=list)
    calls: int = 0

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> AIMessage:
        self.calls += 1
        value = self.replies.pop(0)
        if isinstance(value, Exception):
            raise value
        return AIMessage(content=value)


def settings_with_models(monkeypatch: pytest.MonkeyPatch) -> Settings:
    for key in ("LLM_PROVIDER", "LLM_FAST_MODEL", "LLM_MAIN_MODEL"):
        monkeypatch.delenv(key, raising=False)
    settings = Settings()
    settings.llm.fast_model = "primary"
    settings.llm.fallbacks.fast = ["secondary", "tertiary"]
    return settings


def test_retryable_primary_failure_uses_fallback_in_order_and_records_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = settings_with_models(monkeypatch)
    primary = TextModel(responses=["unused"], replies=[TimeoutError("private")])
    secondary = TextModel(responses=["unused"], replies=[ConnectionError("private")])
    tertiary = TextModel(responses=["unused"], replies=["resolved"])
    fake_models = {"secondary": secondary, "tertiary": tertiary}
    requested: list[tuple[str, float]] = []

    def make_model(role: str, settings: Settings, *, model_name: str, timeout_s: float) -> Any:
        requested.append((model_name, timeout_s))
        return fake_models[model_name]

    monkeypatch.setattr("support_agent.graph.deps.get_chat_model", make_model)
    settings.reliability.retry.max_attempts = 1
    with GraphDeps(settings, fast_model=primary) as deps:
        reply, event = deps.models.invoke("rewrite", "fast", [HumanMessage(content="query")])

    assert reply.content == "resolved"
    assert [name for name, _ in requested] == ["secondary", "tertiary"]
    assert all(0 < timeout <= settings.reliability.timeouts_s.rewrite for _, timeout in requested)
    assert [primary.calls, secondary.calls, tertiary.calls] == [1, 1, 1]
    assert event.model == "tertiary"
    assert event.attempts == 3
    assert event.retries == 0
    assert event.fell_back
    assert event.fallback_error_type == "ConnectionError"
    assert event.error_type is None


def test_graph_records_retry_and_model_and_clears_prior_turn_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = settings_with_models(monkeypatch)
    settings.reliability.retry.base_delay_s = 0
    model = StructuredFake(
        responses=["rewritten"],
        predictions=[
            TimeoutError("private"),
            {"intent": Intent.CHITCHAT_OTHER, "confidence": 1},
            {"intent": Intent.CHITCHAT_OTHER, "confidence": 1},
        ],
    )
    with GraphDeps(settings, fast_model=model) as deps:
        graph = build_graph(deps)
        first = invoke(graph, "hello")
        second = invoke(graph, "hello again")

    assert first["trace"] == ["rewrite", "classify", "fixed"]
    assert first["answered_by_model"] == {"classify": "primary"}
    assert first["reliability_events"][0].retries == 1
    assert first["reliability_events"][0].attempts == 2
    assert second["trace"][-3:] == ["rewrite", "classify", "fixed"]
    assert [event.call_site for event in second["reliability_events"]] == ["rewrite", "classify"]
    assert second["answered_by_model"] == {"rewrite": "primary", "classify": "primary"}


def test_non_retryable_classification_failure_records_no_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = settings_with_models(monkeypatch)
    model = StructuredFake(responses=["unused"], predictions=[RuntimeError("private")])
    with GraphDeps(settings, fast_model=model) as deps:
        result = invoke(build_graph(deps), "hello")

    assert result["trace"] == ["rewrite", "classify", "fixed"]
    assert result["classification_error_type"] == "RuntimeError"
    assert result["answered_by_model"] == {}
    [event] = result["reliability_events"]
    assert event.attempts == 1
    assert event.error_type == "RuntimeError"
    assert event.fell_back is False
    assert "private" not in event.model_dump_json()


def test_timed_out_call_keeps_its_slot_until_the_worker_exits() -> None:
    from threading import Event

    from support_agent.reliability.timeouts import BoundedExecutor

    started = Event()
    finish = Event()
    succeeded = Event()

    def hang() -> None:
        started.set()
        finish.wait()

    executor = BoundedExecutor(1, thread_name_prefix="test-bound")
    try:
        with pytest.raises(TimeoutError):
            executor.run(hang, 0.1)
        assert started.is_set()
        with pytest.raises(TimeoutError):
            executor.run(succeeded.set, 0.1)
        assert not succeeded.is_set()
        finish.set()
        executor.run(succeeded.set, 1)
        assert succeeded.is_set()
    finally:
        finish.set()
        executor.close()


def test_model_events_round_trip_through_postgres_checkpoint_serializer() -> None:
    from support_agent.graph.postgres import checkpoint_serializer
    from support_agent.reliability.events import ReliabilityEvent

    event = ReliabilityEvent(
        call_site="answer",
        dependency="llm:primary",
        role="main",
        model="primary",
        attempts=3,
        retries=2,
        error_type="TimeoutError",
    )
    serializer = checkpoint_serializer()
    result = serializer.loads_typed(serializer.dumps_typed([event]))
    assert result == [event]
    assert isinstance(result[0], ReliabilityEvent)


def test_one_call_whose_retries_all_fail_does_not_open_the_circuit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression (19a smoke run): the breaker counted every retry attempt, so one call that
    # failed three times opened it for every later call. It must count whole calls.
    from support_agent.reliability.circuit import CircuitState

    settings = settings_with_models(monkeypatch)
    settings.llm.fallbacks.fast = []
    settings.reliability.retry.base_delay_s = 0
    settings.reliability.retry.max_delay_s = 0
    attempts = settings.reliability.retry.max_attempts
    settings.reliability.circuit.failure_threshold = attempts
    failures: list[str | Exception] = [ConnectionError("private")] * attempts
    model = TextModel(responses=["unused"], replies=[*failures, *failures, *failures, "ok"])
    with GraphDeps(settings, fast_model=model) as deps:
        for expected_state in (CircuitState.CLOSED, CircuitState.CLOSED, CircuitState.OPEN):
            with pytest.raises(ConnectionError):
                deps.models.invoke("rewrite", "fast", [HumanMessage(content="query")])
            assert deps.circuits.state("llm:primary") is expected_state
    assert model.calls == attempts * attempts
