"""Bridge a synchronous, checkpointed graph turn into async SSE events."""

import logging
from collections.abc import AsyncGenerator, Generator
from time import perf_counter
from typing import Any

from anyio import CancelScope, to_thread
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from starlette.concurrency import iterate_in_threadpool

from support_agent.api.events import SseEvent, events_for_update
from support_agent.gate.evidence import GateResult
from support_agent.graph.handoff import HandoffReason
from support_agent.graph.state import ConversationState

Graph = CompiledStateGraph[ConversationState, None, Any, Any]
TurnInput = dict[str, Any] | Command[Any]
logger = logging.getLogger(__name__)


def _turn_events(
    graph: Graph,
    input_or_command: TurnInput,
    config: RunnableConfig,
    chunk_words: int,
) -> Generator[SseEvent, None, None]:
    started = perf_counter()
    usage = UsageMetadataCallbackHandler()
    config = {**config, "callbacks": [usage]}
    terminal: list[SseEvent] = []
    for updates in graph.stream(input_or_command, config, stream_mode="updates", durability="sync"):
        for node, update in updates.items():
            if node == "__interrupt__":
                update = update[0].value
            events = events_for_update(node, update or {}, chunk_words)
            if node == "classify":
                yield from events
            elif events:
                # A refund can hand off before its last edge. Publish only its final reply.
                terminal = events

    snapshot = graph.get_state(config)
    gate = snapshot.values.get("gate")
    trace = snapshot.values.get("trace", [])
    boundary = "classify" if isinstance(input_or_command, Command) else "rewrite"
    start = max((i for i, name in enumerate(trace) if name == boundary), default=-1)
    if isinstance(input_or_command, Command):
        start += 1
    nodes = set(graph.nodes) | {"refund_identify"}
    done = SseEvent(
        name="done",
        data={
            "latency_ms": (perf_counter() - started) * 1000,
            "usage": usage.usage_metadata,
            "trace": [name for name in trace[max(start, 0) :] if name in nodes],
            "gate": GateResult.model_validate(gate).model_dump(mode="json") if gate else None,
        },
    )
    yield from terminal
    yield done


def failure_events(
    error: Exception, conversation_id: str, system_error_message: str
) -> list[SseEvent]:
    error_type = type(error).__name__
    logger.error("Chat turn %s failed: %s", conversation_id, error_type)
    return [
        SseEvent(name="error", data={"error_type": error_type}),
        SseEvent(
            name="handoff",
            data={"reason": HandoffReason.SYSTEM_ERROR, "message": system_error_message},
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
) -> AsyncGenerator[SseEvent, None]:
    turn = _turn_events(graph, input_or_command, config, chunk_words)
    try:
        async for event in iterate_in_threadpool(turn):
            yield event
    except Exception as error:
        for event in failure_events(error, conversation_id, system_error_message):
            yield event
    finally:
        with CancelScope(shield=True):
            await to_thread.run_sync(turn.close)
