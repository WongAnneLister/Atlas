"""Validated conversation state shared by the fixed workflow nodes."""

from typing import Annotated, Any

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from support_agent.graph.intents import Intent, Path
from support_agent.retrieval.types import RetrievedChunk


class ConversationState(BaseModel):
    messages: Annotated[list[AnyMessage], add_messages] = Field(default_factory=list)
    customer_id: str | None = None
    rewritten_query: str = ""
    intent: Intent | None = None
    intent_confidence: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)
    path: Path | None = None
    intent_low_confidence: bool = False
    classification_failed: bool = False
    classification_error_type: str | None = None
    classifier_model: str | None = None
    retrieval: list[RetrievedChunk] = Field(default_factory=list)
    gate: dict[str, Any] | None = None
    order_context: dict[str, Any] | None = None
    handoff: dict[str, Any] | None = None
    answer: str = ""
    citations: list[str] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)
