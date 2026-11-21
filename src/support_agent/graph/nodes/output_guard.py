"""Publish only final replies that pass the output checks."""

import json
from contextlib import suppress
from typing import Any

from langchain_core.messages import AIMessage

from support_agent.graph.deps import GraphDeps
from support_agent.graph.handoff import PROMPTS, HandoffReason, make_handoff
from support_agent.graph.state import ConversationState
from support_agent.guardrails.output import OutputChecks, OutputFlag
from support_agent.guardrails.pii import find_pii


def _evidence(state: ConversationState) -> list[str]:
    """Cited policy text and the customer-scoped order data of this turn."""
    chunks = {chunk.chunk_id: chunk.text for chunk in state.retrieval}
    texts = [chunks.get(record.chunk_id, "") for record in state.citations]
    if state.order_context:
        texts.append(json.dumps(state.order_context, default=str))
    return texts


class OutputGuard:
    def __init__(self, deps: GraphDeps) -> None:
        self.deps = deps
        self.settings = deps.settings.guardrails.output
        self.checks = OutputChecks(self.settings, PROMPTS)

    def _violation(self, state: ConversationState) -> OutputFlag | None:
        if self.settings.prompt_leak and self.checks.prompt_leaked(state.answer):
            return "prompt_leak"
        if self.settings.foreign_pii:
            allowed_email = None
            if state.customer_id and any(match.kind == "email" for match in find_pii(state.answer)):
                # Unavailable ownership evidence cannot authorize disclosure.
                with suppress(Exception):
                    allowed_email = self.deps.guarded_orders().customer_email(state.customer_id)
            if self.checks.foreign_pii(state.answer, allowed_email, _evidence(state)):
                return "foreign_pii"
        if self.settings.commitments and self.checks.unbacked_commitment(state):
            return "unbacked_commitment"
        return None

    def __call__(self, state: ConversationState) -> dict[str, Any]:
        trace = [*state.trace, "output_guard"]
        violation = self._violation(state)
        if violation is None:
            return {
                "answer": state.answer,
                "messages": [AIMessage(content=state.answer)] if state.answer else [],
                "handoff": state.handoff,
                "citations": [citation.model_dump() for citation in state.citations],
                "trace": trace,
            }
        original = state.messages
        unsafe = original[-1] if original and isinstance(original[-1], AIMessage) else None
        messages = original[:-1] if unsafe is not None else original
        flags = [*state.guardrail_flags, violation]
        current = state.model_copy(update={"messages": messages, "guardrail_flags": flags})
        update = make_handoff(current, HandoffReason.GUARDRAIL_BLOCKED)
        if unsafe is not None:
            update["messages"][0] = update["messages"][0].model_copy(update={"id": unsafe.id})
        return {
            **update,
            "citations": [],
            "guardrail_flags": flags,
            "output_guard_flag": violation,
            "answer_status": "guardrail_blocked",
            "trace": trace,
        }
