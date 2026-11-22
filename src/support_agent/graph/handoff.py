"""Shared, validated handoff records and customer-facing templates."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from langchain_core.messages import AIMessage, AnyMessage
from pydantic import BaseModel, Field

from support_agent.gate.evidence import GateResult
from support_agent.graph.coverage import CoverageAnswer
from support_agent.graph.intents import Intent
from support_agent.graph.parts import QueryPart
from support_agent.graph.turn_identity import action_key, current_graph_config, turn_message_id
from support_agent.retrieval.filters import RetrievalFilters
from support_agent.retrieval.types import RetrievedChunk

if TYPE_CHECKING:
    from support_agent.graph.state import ConversationState

PROMPTS = Path(__file__).with_name("prompts")


class HandoffReason(StrEnum):
    SYSTEM_ERROR = "system_error"
    USER_REQUESTED = "user_requested"
    GUARDRAIL_BLOCKED = "guardrail_blocked"
    COMPLAINT = "complaint"
    LOW_EVIDENCE = "low_evidence"
    LOW_GROUNDING = "low_grounding"
    RETRIEVAL_ERROR = "retrieval_error"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    ANSWER_ERROR = "answer_error"
    INVALID_ANSWER = "invalid_answer"
    INCOMPLETE_EVIDENCE = "incomplete_evidence"
    UNSUPPORTED_PART = "unsupported_part"
    AGENT_STEP_CAP = "agent_step_cap"
    TOOL_ERROR = "tool_error"
    ORDER_NOT_FOUND = "order_not_found"
    POLICY_REQUIRES_HUMAN = "policy_requires_human"


class HandoffPayload(BaseModel):
    reason: HandoffReason
    conversation: list[AnyMessage]
    rewritten_query: str
    intent: Intent | None
    retrieval_build_id: str | None = None
    retrieval_snapshot: list[RetrievedChunk] = Field(default_factory=list)
    filters: RetrievalFilters | None = None
    filters_applied: bool = False
    gate: GateResult | None = None
    coverage: CoverageAnswer | None = None
    parts: list[QueryPart] = Field(default_factory=list)
    customer_message: str | None = None
    order_context: dict[str, Any] | None = None
    guardrail_flags: list[str] = Field(default_factory=list)
    created_at: datetime
    idempotency_key: str | None = None
    trace_id: str | None = None


def load_templates(name: str) -> dict[str, str]:
    data = yaml.safe_load((PROMPTS / name).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not all(
        isinstance(key, str) and isinstance(value, str) and value.strip()
        for key, value in data.items()
    ):
        raise ValueError(f"Invalid reply templates: {name}")
    return data


def mark_parts_handed_off(parts: list[QueryPart], reason: str) -> list[QueryPart]:
    return [
        part.model_copy(
            update={
                "answered": False,
                "handed_off": True,
                "cited_section_ids": [],
                "failure_reason": part.failure_reason or reason,
            }
        )
        for part in parts
    ]


def make_handoff(
    state: ConversationState, reason: HandoffReason, *, customer_message: str | None = None
) -> dict[str, Any]:
    answer = customer_message or load_templates("handoff_messages.yaml")[reason.value]
    parts = state.parts if state.route_source == "parts" else []
    targeted = reason == HandoffReason.UNSUPPORTED_PART
    if targeted:
        parts = [part for part in parts if part.handed_off]
        # Keep the local source snapshots in each part, including local rerank scores.
        snapshot = {chunk.chunk_id: chunk for part in parts for chunk in part.retrieval}
        retrieval = list(snapshot.values())
    else:
        retrieval = state.retrieval
    message = AIMessage(content=answer)
    config = current_graph_config()
    trace_id = config.get("metadata", {}).get("trace_id")
    payload = HandoffPayload(
        idempotency_key=action_key(config, turn_message_id(state.messages), "handoff"),
        trace_id=trace_id if isinstance(trace_id, str) else None,
        reason=reason,
        conversation=[*state.messages, message],
        rewritten_query=state.rewritten_query,
        intent=state.intent,
        retrieval_snapshot=retrieval,
        retrieval_build_id=state.retrieval_build_id,
        filters=state.filters,
        filters_applied=state.filters_applied,
        gate=None if targeted else state.gate,
        coverage=None if targeted else state.coverage,
        parts=parts,
        customer_message=customer_message,
        order_context=state.order_context,
        guardrail_flags=state.guardrail_flags,
        created_at=datetime.now(UTC),
    )
    return {"answer": answer, "messages": [message], "handoff": payload}
