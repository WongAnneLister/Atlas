"""Validated conversation state shared by the fixed workflow nodes."""

from typing import Annotated, Any, Literal

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from support_agent.gate.evidence import GateResult
from support_agent.graph.coverage import CoverageAnswer
from support_agent.graph.handoff import HandoffPayload
from support_agent.graph.intents import Intent, Path
from support_agent.guardrails.input import InputAction
from support_agent.reliability.events import ReliabilityEvent
from support_agent.retrieval.filters import RetrievalFilters
from support_agent.retrieval.types import RetrievedChunk


class CitationRecord(BaseModel):
    n: int = Field(gt=0)
    chunk_id: str
    section_id: str
    heading_path: str


class ConversationState(BaseModel):
    messages: Annotated[list[AnyMessage], add_messages] = Field(default_factory=list)
    customer_id: str | None = None
    rewritten_query: str = ""
    input_guard_action: InputAction = "allow"
    guardrail_flags: list[str] = Field(default_factory=list)
    output_guard_flag: str | None = None
    intent: Intent | None = None
    intent_confidence: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)
    path: Path | None = None
    intent_low_confidence: bool = False
    classification_failed: bool = False
    classification_error_type: str | None = None
    classifier_model: str | None = None
    answered_by_model: dict[str, str] = Field(default_factory=dict)
    reliability_events: list[ReliabilityEvent] = Field(default_factory=list)
    retrieval_build_id: str | None = None
    retrieval: list[RetrievedChunk] = Field(default_factory=list)
    filters: RetrievalFilters | None = None
    filters_applied: bool = False
    gate: GateResult | None = None
    retrieval_error_type: str | None = None
    retrieval_dependency_unavailable: bool = False
    answer_status: Literal[
        "not_attempted",
        "answered",
        "model_error",
        "invalid_output",
        "invalid_citation",
        "insufficient_coverage",
        "implied_by_absence",
        "invalid_evidence",
        "guardrail_blocked",
    ] = "not_attempted"
    answer_error_type: str | None = None
    coverage: CoverageAnswer | None = None
    order_context: dict[str, Any] | None = None
    refund_candidates: list[dict[str, Any]] = Field(default_factory=list)
    refund_order_id: str | None = None
    refund_policy_query: str = ""
    refund_decision: dict[str, Any] | None = None
    refund_request: dict[str, Any] | None = None
    handoff: HandoffPayload | None = None
    tool_errors: int = Field(default=0, ge=0)
    consecutive_tool_errors: int = Field(default=0, ge=0)
    agent_steps: int = Field(default=0, ge=0)
    # Set by the order loop when no tool was called; routes to retrieval.
    fallback_to_knowledge: bool = False
    answer: str = ""
    citations: list[CitationRecord] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)
