"""Typed query parts and fan-out records for the knowledge path."""

from pydantic import BaseModel, Field

from support_agent.gate.evidence import GateResult
from support_agent.graph.intents import Intent
from support_agent.reliability.events import ReliabilityEvent
from support_agent.retrieval.filters import RetrievalFilters
from support_agent.retrieval.types import RetrievedChunk


class QueryPart(BaseModel):
    text: str = Field(min_length=1)
    key_terms: list[str] = Field(default_factory=list)
    intent: Intent | None = None
    classification_failed: bool = False
    retrieval: list[RetrievedChunk] = Field(default_factory=list)
    filters: RetrievalFilters | None = None
    filters_applied: bool = False
    gate: GateResult | None = None
    source_numbers: list[int] = Field(default_factory=list)
    failure_reason: str | None = None
    answered: bool = False
    handed_off: bool = False
    cited_section_ids: list[str] = Field(default_factory=list)


class PartRetrievalRequest(BaseModel):
    index: int = Field(ge=0)
    text: str
    rewritten_query: str


class PartRetrievalResult(BaseModel):
    index: int = Field(ge=0)
    retrieval: list[RetrievedChunk] = Field(default_factory=list)
    filters: RetrievalFilters | None = None
    filters_applied: bool = False
    retrieval_build_id: str | None = None
    retrieval_error_type: str | None = None
    retrieval_dependency_unavailable: bool = False
    reliability_events: list[ReliabilityEvent] = Field(default_factory=list)
