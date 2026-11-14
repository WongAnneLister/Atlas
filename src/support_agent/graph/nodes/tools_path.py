"""Bounded read-only order loop with per-turn facts and safe error feedback."""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from pydantic import ValidationError

from support_agent.graph.deps import GraphDeps
from support_agent.graph.handoff import PROMPTS, HandoffReason, make_handoff
from support_agent.graph.intents import Intent
from support_agent.graph.state import ConversationState
from support_agent.graph.tools import ToolResult, build_order_tools
from support_agent.orders.models import OrderNotFound
from support_agent.orders.service import OrderService

logger = logging.getLogger(__name__)


def execute_tool(tools: dict[str, BaseTool], name: str, arguments: dict[str, Any]) -> ToolResult:
    """Only short, public errors reach the model; exception bodies stay private."""
    if name not in tools:
        return ToolResult(ok=False, error="unknown_tool")
    try:
        return ToolResult(ok=True, data=tools[name].invoke(arguments))
    except OrderNotFound:
        return ToolResult(ok=False, error="order_not_found")
    except (ValidationError, TypeError, ValueError):
        return ToolResult(ok=False, error="invalid_tool_arguments")
    except Exception as error:
        logger.warning("Order tool failed: %s", type(error).__name__)
        return ToolResult(ok=False, error="order_service_unavailable")


def _updates(state: ConversationState) -> dict[str, Any]:
    return {
        "trace": state.trace,
        "order_context": state.order_context,
        "tool_errors": state.tool_errors,
        "consecutive_tool_errors": state.consecutive_tool_errors,
        "agent_steps": state.agent_steps,
    }


class ToolsPath:
    def __init__(self, deps: GraphDeps) -> None:
        self.deps = deps
        self.prompt = (PROMPTS / "tools_path.md").read_text(encoding="utf-8")

    def __call__(self, state: ConversationState) -> dict[str, Any]:
        current = state.model_copy(deep=True)
        current.trace.append("tools")
        # These branches do not create or invoke the main model.
        if state.intent == Intent.TALK_TO_HUMAN:
            return {**_updates(current), **make_handoff(current, HandoffReason.USER_REQUESTED)}
        if not state.customer_id or not state.customer_id.strip():
            return {**_updates(current), **make_handoff(current, HandoffReason.TOOL_ERROR)}
        settings = self.deps.settings
        service = self.deps.order_service or OrderService(settings=settings.orders)
        tools = build_order_tools(service, state.customer_id)
        by_name = {tool.name: tool for tool in tools}
        messages: list[BaseMessage] = [
            SystemMessage(content=self.prompt),
            HumanMessage(content=state.rewritten_query),
        ]
        try:
            model = self.deps.model("main").bind_tools(tools)
            return self._loop(current, model, by_name, messages)
        except Exception as error:
            logger.warning("Order loop failed: %s", type(error).__name__)
            return {**_updates(current), **make_handoff(current, HandoffReason.TOOL_ERROR)}

    def _loop(
        self,
        state: ConversationState,
        model: Any,
        tools: dict[str, BaseTool],
        messages: list[BaseMessage],
    ) -> dict[str, Any]:
        cfg = self.deps.settings.agent
        had_success = False
        called_any = False
        last_error: str | None = None
        for step in range(cfg.max_steps):
            state.agent_steps = step + 1
            response = model.invoke(messages)
            if not isinstance(response, AIMessage) or response.invalid_tool_calls:
                return {**_updates(state), **make_handoff(state, HandoffReason.TOOL_ERROR)}
            messages.append(response)
            if not response.tool_calls:
                if cfg.knowledge_fallback and not called_any:
                    # The model judged this is not an order lookup. Its free text is
                    # not grounded, so it is dropped; the gated knowledge path answers.
                    state.trace.append("tools_fallback")
                    return {**_updates(state), "fallback_to_knowledge": True}
                answer = response.content
                if (
                    had_success
                    and state.consecutive_tool_errors == 0
                    and isinstance(answer, str)
                    and answer.strip()
                ):
                    return {
                        **_updates(state),
                        "answer": answer.strip(),
                        "messages": [AIMessage(content=answer.strip())],
                    }
                reason = (
                    HandoffReason.ORDER_NOT_FOUND
                    if last_error == "order_not_found"
                    else HandoffReason.TOOL_ERROR
                )
                return {**_updates(state), **make_handoff(state, reason)}
            if len(response.tool_calls) > cfg.max_tool_calls_per_step:
                return {**_updates(state), **make_handoff(state, HandoffReason.AGENT_STEP_CAP)}
            called_any = True
            for call in response.tool_calls:
                # Trace only the accepted public argument; never trace forged customer ids.
                args = {key: value for key, value in call["args"].items() if key == "order_id"}
                short = json.dumps(args, sort_keys=True, ensure_ascii=True)[: cfg.trace_max_chars]
                state.trace.append(f"tool_call:{call['name']}:{short}")
                result = execute_tool(tools, call["name"], call["args"])
                last_error = result.error
                if result.ok:
                    had_success = True
                    state.consecutive_tool_errors = 0
                    context = dict(state.order_context or {})
                    context[call["name"]] = result.data
                    state.order_context = context
                else:
                    state.tool_errors += 1
                    state.consecutive_tool_errors += 1
                summary = result.model_dump_json()[: cfg.trace_max_chars]
                state.trace.append(f"tool_result:{call['name']}:{summary}")
                messages.append(
                    ToolMessage(content=result.model_dump_json(), tool_call_id=call["id"])
                )
                if state.consecutive_tool_errors >= cfg.max_consecutive_tool_errors:
                    return {**_updates(state), **make_handoff(state, HandoffReason.TOOL_ERROR)}
        return {**_updates(state), **make_handoff(state, HandoffReason.AGENT_STEP_CAP)}
