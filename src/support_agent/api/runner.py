"""Bridge a synchronous, checkpointed graph turn into async SSE events."""

import logging
from collections.abc import AsyncGenerator, Generator
from time import perf_counter
from typing import Any

from anyio import CancelScope, to_thread
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from starlette.concurrency import iterate_in_threadpool

from support_agent.api.events import SseEvent, events_for_update
from support_agent.config import CostSettings
from support_agent.gate.evidence import GateResult
from support_agent.graph.handoff import HandoffReason
from support_agent.graph.state import ConversationState
from support_agent.observability.cost import UsageLedger, cost_usd
from support_agent.observability.metrics import AtlasMetrics
from support_agent.observability.tracing import TurnTrace

Graph = CompiledStateGraph[ConversationState, None, Any, Any]
TurnInput = dict[str, Any] | Command[Any]
logger = logging.getLogger(__name__)


def _turn_events(
    graph: Graph,
    input_or_command: TurnInput,
    config: RunnableConfig,
    chunk_words: int,
    trace: TurnTrace,
    costs: CostSettings,
    metrics: AtlasMetrics | None,
) -> Generator[SseEvent, None, None]:
    try:
        yield from _traced_turn(graph, input_or_command, config, chunk_words, trace, costs, metrics)
    except Exception as error:
        trace.finish(None, error_type=type(error).__name__)
        raise
    finally:
        # A closed stream (client gone) still ends the root span; finish is idempotent.
        trace.finish(None, error_type="stream_closed")


def _traced_turn(
    graph: Graph,
    input_or_command: TurnInput,
    config: RunnableConfig,
    chunk_words: int,
    trace: TurnTrace,
    costs: CostSettings,
    metrics: AtlasMetrics | None,
) -> Generator[SseEvent, None, None]:
    started = perf_counter()
    usage = UsageLedger()
    config = {
        **config,
        "callbacks": [usage, *trace.callbacks],
        "metadata": {**config.get("metadata", {}), **trace.config_metadata},
    }
    terminal: list[SseEvent] = []
    for updates in graph.stream(input_or_command, config, stream_mode="updates", durability="sync"):
        for node, update in updates.items():
            if node == "__interrupt__":
                update = update[0].value
            elif metrics and update:
                metrics.graph_update(update)
            events = events_for_update(node, update or {}, chunk_words)
            if node == "classify":
                yield from events
            elif events:
                # A refund can hand off before its last edge. Publish only its final reply.
                terminal = events

    snapshot = graph.get_state(config)
    gate = snapshot.values.get("gate")
    route = snapshot.values.get("trace", [])
    boundary = "classify" if isinstance(input_or_command, Command) else "rewrite"
    start = max((i for i, name in enumerate(route) if name == boundary), default=-1)
    if isinstance(input_or_command, Command):
        start += 1
    nodes = set(graph.nodes) | {"refund_identify"}
    done = SseEvent(
        name="done",
        data={
            "latency_ms": (perf_counter() - started) * 1000,
            "usage": {model: item.model_dump() for model, item in usage.by_model.items()},
            "llm_calls": usage.calls,
            "cost_usd": cost_usd(usage.by_model, costs),
            "trace": [name for name in route[max(start, 0) :] if name in nodes],
            "gate": GateResult.model_validate(gate).model_dump(mode="json") if gate else None,
        },
    )
    trace.finish(snapshot.values)
    yield from terminal
    yield done


def failure_events(
    error: Exception,
    conversation_id: str,
    system_error_message: str,
    *,
    trace_id: str | None = None,
    metrics: AtlasMetrics | None = None,
) -> list[SseEvent]:
    error_type = type(error).__name__
    logger.error("Chat turn failed trace_id=%s: %s", trace_id or conversation_id, error_type)
    if metrics:
        metrics.handoff(HandoffReason.SYSTEM_ERROR)
    handoff = {"reason": HandoffReason.SYSTEM_ERROR, "message": system_error_message}
    if trace_id:
        handoff["trace_id"] = trace_id
    return [
        SseEvent(name="error", data={"error_type": error_type}),
        SseEvent(
            name="handoff",
            data=handoff,
        ),
    ]


async def run_turn(
    graph: Graph,
    input_or_command: TurnInput,
    config: RunnableConfig,
    *,
    chunk_words: int,
    conversation_id: str,
    system_error_message: str,
    trace: TurnTrace,
    costs: CostSettings,
    metrics: AtlasMetrics | None = None,
    trace_id: str | None = None,
) -> AsyncGenerator[SseEvent, None]:
    turn = _turn_events(graph, input_or_command, config, chunk_words, trace, costs, metrics)
    try:
        async for event in iterate_in_threadpool(turn):
            yield event
    except Exception as error:
        for event in failure_events(
            error, conversation_id, system_error_message, trace_id=trace_id, metrics=metrics
        ):
            yield event
    finally:
        with CancelScope(shield=True):
            await to_thread.run_sync(turn.close)
