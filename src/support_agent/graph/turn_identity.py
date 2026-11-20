"""Stable workflow action keys derived from the active thread and turn."""

from collections.abc import Sequence
from json import dumps
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from langchain_core.messages import AnyMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_config


def current_graph_config() -> RunnableConfig:
    try:
        return get_config()
    except RuntimeError:
        # Standalone node calls used by offline evaluation have no thread.
        return {}


def turn_message_id(messages: Sequence[AnyMessage]) -> str | None:
    return next(
        (message.id for message in reversed(messages) if isinstance(message, HumanMessage)), None
    )


def action_key(
    config: RunnableConfig, turn_id: str | None, action: Literal["refund_request", "handoff"]
) -> str | None:
    thread_id = config.get("configurable", {}).get("thread_id")
    if not isinstance(thread_id, str) or not thread_id or not turn_id:
        return None
    return uuid5(NAMESPACE_URL, dumps(["atlas-action", thread_id, turn_id, action])).hex
