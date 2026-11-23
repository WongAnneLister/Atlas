"""Bounded read-only order loop with per-turn facts and safe error feedback."""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from pydantic import ValidationError

from support_agent.context.budget import ContextOverflow
from support_agent.graph.deps import GraphDeps
from support_agent.graph.handoff import PROMPTS, HandoffReason, load_templates, make_handoff
from support_agent.graph.intents import Intent
from support_agent.graph.model_data import order_block
from support_agent.graph.order_grounding import check_order_answer_reliably
from support_agent.graph.order_replies import REPLY_TOOL, Lookup, render_order_reply, reply_tool
from support_agent.graph.state import ConversationState
from support_agent.graph.tools import ToolResult, build_order_tools
from support_agent.orders.models import OrderNotFound
from support_agent.reliability.guards import is_dependency_failure

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
        code = (
            "dependency_unavailable"
            if is_dependency_failure(error)
            else "order_service_unavailable"
        )
        return ToolResult(ok=False, error=code)


def _lookup_failed(last_error: str | None) -> HandoffReason:
    if last_error == "order_not_found":
        return HandoffReason.ORDER_NOT_FOUND
    return HandoffReason.TOOL_ERROR


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
        self.grounding_prompt = (PROMPTS / "order_grounding.md").read_text(encoding="utf-8")
        template = deps.settings.agent.order_replies == "template"
        prompt_file = "tools_path_template.md" if template else "tools_path.md"
        self.prompt = (PROMPTS / prompt_file).read_text(encoding="utf-8")
        self.reminder = "Finish now by calling the reply tool; do not write the reply yourself."
        self.templates = load_templates("order_replies.yaml") if template else {}

    def __call__(self, state: ConversationState) -> dict[str, Any]:
        current = state.model_copy(deep=True)
        current.trace.append("tools")
        # These branches do not create or invoke the main model.
        if state.intent == Intent.TALK_TO_HUMAN:
            return {**_updates(current), **make_handoff(current, HandoffReason.USER_REQUESTED)}
        if not state.customer_id or not state.customer_id.strip():
            return {**_updates(current), **make_handoff(current, HandoffReason.TOOL_ERROR)}
        settings = self.deps.settings
        service = self.deps.guarded_orders()
        tools = build_order_tools(service, state.customer_id)
        by_name = {tool.name: tool for tool in tools}
        try:
            bound = list(tools)
            if settings.agent.order_replies == "template":
                bound.append(reply_tool())
            return self._loop(current, bound, by_name, [])
        except ContextOverflow:
            cb = getattr(self.deps.observer, "context_overflow", None)
            if callable(cb):
                cb("tools")
            return {**_updates(current), **make_handoff(current, HandoffReason.CONTEXT_OVERFLOW)}
        except Exception as error:
            logger.warning("Order loop failed: %s", type(error).__name__)
            reason = (
                HandoffReason.DEPENDENCY_UNAVAILABLE
                if is_dependency_failure(error)
                else HandoffReason.TOOL_ERROR
            )
            return {**_updates(current), **make_handoff(current, reason)}

    def _loop(
        self,
        state: ConversationState,
        bound: list[BaseTool],
        tools: dict[str, BaseTool],
        messages: list[BaseMessage],
    ) -> dict[str, Any]:
        cfg = self.deps.settings.agent
        template = cfg.order_replies == "template"
        had_success = False
        called_any = False
        reminded = False
        last_error: str | None = None
        lookups: list[Lookup] = []
        for step in range(cfg.max_steps):
            state.agent_steps = step + 1
            built = self.deps.context_builder().build(
                "tools",
                task_prompt=self.prompt,
                user_text=state.rewritten_query,
                history=state.messages[:-1],
                tool_names=[tool.name for tool in bound],
                current_date=self.deps.settings.orders.today,
                extra_l4_messages=messages,
            )
            response, _ = self.deps.models.invoke("tools", "main", built, tools=bound)
            if not isinstance(response, AIMessage) or response.invalid_tool_calls:
                return {**_updates(state), **make_handoff(state, HandoffReason.TOOL_ERROR)}
            messages.append(response)
            if not response.tool_calls:
                if cfg.knowledge_fallback and not called_any:
                    # The model judged this is not an order lookup. Its free text is
                    # not grounded, so it is dropped; the gated knowledge path answers.
                    state.trace.append("tools_fallback")
                    return {**_updates(state), "fallback_to_knowledge": True}
                if template:
                    if reminded:
                        return self._to_knowledge(state)
                    # Free text is never released in template mode; ask for the decision.
                    reminded = True
                    state.trace.append("reply_reminder")
                    messages.append(HumanMessage(content=self.reminder))
                    continue
                answer = response.content
                if (
                    had_success
                    and state.consecutive_tool_errors == 0
                    and isinstance(answer, str)
                    and answer.strip()
                ):
                    if cfg.order_grounding and not self._grounded(state, answer.strip()):
                        return self._to_knowledge(state)
                    return {
                        **_updates(state),
                        "answer": answer.strip(),
                        "messages": [AIMessage(content=answer.strip())],
                    }
                return {**_updates(state), **make_handoff(state, _lookup_failed(last_error))}
            lookups_called = [c for c in response.tool_calls if c["name"] != REPLY_TOOL]
            if len(lookups_called) > cfg.max_tool_calls_per_step:
                return {**_updates(state), **make_handoff(state, HandoffReason.AGENT_STEP_CAP)}
            called_any = True
            for call in lookups_called:
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
                    order_id = args.get("order_id")
                    lookups.append((call["name"], str(order_id) if order_id else None, result.data))
                else:
                    state.tool_errors += 1
                    state.consecutive_tool_errors += 1
                summary = result.model_dump_json()[: cfg.trace_max_chars]
                state.trace.append(f"tool_result:{call['name']}:{summary}")
                data_block = order_block(result.model_dump_json())
                messages.append(ToolMessage(content=data_block, tool_call_id=call["id"]))
                if last_error == "dependency_unavailable":
                    return {
                        **_updates(state),
                        **make_handoff(state, HandoffReason.DEPENDENCY_UNAVAILABLE),
                    }
                if state.consecutive_tool_errors >= cfg.max_consecutive_tool_errors:
                    return {**_updates(state), **make_handoff(state, HandoffReason.TOOL_ERROR)}
            decision = next((c for c in response.tool_calls if c["name"] == REPLY_TOOL), None)
            if template and decision is not None:
                return self._reply(state, decision["args"], lookups, last_error)
        return {**_updates(state), **make_handoff(state, HandoffReason.AGENT_STEP_CAP)}

    def _reply(
        self,
        state: ConversationState,
        args: dict[str, Any],
        lookups: list[Lookup],
        last_error: str | None,
    ) -> dict[str, Any]:
        """The model only decides; code writes the reply from this turn's lookups."""
        if args.get("answer_from_order_data") is not True:
            state.trace.append("reply:not_order_data")
            return self._to_knowledge(state)
        if not lookups or state.consecutive_tool_errors:
            return {**_updates(state), **make_handoff(state, _lookup_failed(last_error))}
        answer = render_order_reply(lookups, self.templates)
        state.trace.append("reply:order_data")
        return {**_updates(state), "answer": answer, "messages": [AIMessage(content=answer)]}

    def _grounded(self, state: ConversationState, answer: str) -> bool:
        """Fails closed: a checker error counts as ungrounded."""
        result = check_order_answer_reliably(
            self.deps.models,
            self.grounding_prompt,
            state.order_context,
            answer,
        )
        if result.attempts > 1:
            state.trace.append(f"grounding_retry:{result.attempts - 1}")
        if result.status == "error":
            state.trace.append("grounding_error")
        elif result.missing:
            state.trace.append(f"ungrounded:{len(result.missing)}")
        return result.status == "grounded"

    def _to_knowledge(self, state: ConversationState) -> dict[str, Any]:
        """Nothing from the order model is released; the gated knowledge path answers."""
        if self.deps.settings.agent.knowledge_fallback:
            state.trace.append("tools_fallback")
            return {**_updates(state), "fallback_to_knowledge": True}
        return {**_updates(state), **make_handoff(state, HandoffReason.INVALID_ANSWER)}
