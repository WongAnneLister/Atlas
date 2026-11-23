"""Strict structural eligibility rules for the knowledge answer cache."""

from __future__ import annotations

import re

from langchain_core.messages import AnyMessage, ToolMessage

from support_agent.cache.settings import CacheSettings
from support_agent.graph.intents import Intent, Path
from support_agent.graph.state import ConversationState
from support_agent.guardrails.pii import find_pii

_ELIGIBLE_INTENTS = frozenset({Intent.POLICY_QUESTION, Intent.PRODUCT_QUESTION})
_CUSTOMER_DATA_PATTERNS = (
    re.compile(r"\bORD-\d+\b", re.IGNORECASE),
    re.compile(r"\bCUST-\d+\b", re.IGNORECASE),
    re.compile(r"\bTRK-[A-Z0-9-]+\b", re.IGNORECASE),
)


def has_customer_specific_text(text: str) -> bool:
    if not text:
        return False
    if any(pattern.search(text) for pattern in _CUSTOMER_DATA_PATTERNS):
        return True
    return bool(find_pii(text))


def _message_text(message: AnyMessage) -> str:
    content = message.content
    return content if isinstance(content, str) else ""


def _recent_messages(messages: list[AnyMessage], recent_turns: int) -> list[AnyMessage]:
    if recent_turns <= 0 or not messages:
        return []
    # Each turn is roughly two messages (human + assistant); inspect a bounded tail.
    window = recent_turns * 2 + 2
    return messages[-window:]


def has_customer_context_in_history(messages: list[AnyMessage], recent_turns: int) -> bool:
    for message in _recent_messages(messages, recent_turns):
        if isinstance(message, ToolMessage):
            return True
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            return True
        if has_customer_specific_text(_message_text(message)):
            return True
    return False


def answer_cache_lookup_eligibility(
    state: ConversationState, settings: CacheSettings
) -> tuple[bool, str]:
    """Return (eligible, reason) before retrieval/generation on the knowledge path."""
    if not settings.enabled or not settings.answer.enabled:
        return False, "cache_disabled"
    if state.path != Path.KNOWLEDGE:
        return False, "non_knowledge_path"
    if state.intent not in _ELIGIBLE_INTENTS:
        return False, "ineligible_intent"
    if state.route_source != "whole":
        return False, "multipart_route"
    if state.fallback_to_knowledge:
        return False, "tools_fallback"
    if state.input_guard_action != "allow" or state.guardrail_flags or state.output_guard_flag:
        return False, "guardrail_flagged"
    if (
        state.order_context is not None
        or state.refund_order_id is not None
        or state.refund_candidates
        or state.refund_request is not None
    ):
        return False, "order_context_present"
    if not state.rewritten_query.strip():
        return False, "empty_query"
    if has_customer_specific_text(state.rewritten_query):
        return False, "customer_data_in_query"
    if has_customer_context_in_history(state.messages, settings.answer.recent_turns):
        return False, "customer_data_in_history"
    return True, "eligible"


def answer_cache_write_eligibility(
    state: ConversationState,
    settings: CacheSettings,
    *,
    grounding_enabled: bool,
) -> tuple[bool, str]:
    """Return (eligible, reason) after gate, grounding, and output guard all pass."""
    ok, reason = answer_cache_lookup_eligibility(state, settings)
    if not ok:
        return False, reason
    if state.gate is None or not state.gate.passed:
        return False, "gate_not_passed"
    if state.handoff is not None:
        return False, "handoff_present"
    if state.answer_status != "answered":
        return False, "not_answered"
    if not state.answer.strip() or not state.citations:
        return False, "missing_answer_or_citations"
    if state.output_guard_flag is not None:
        return False, "output_guard_flagged"
    if grounding_enabled and state.claims is None:
        return False, "grounding_missing"
    if not state.retrieval_build_id:
        return False, "missing_build_id"
    return True, "eligible"
