"""Public API payloads."""

from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints

from support_agent.handoff.models import ResolutionLabel
from support_agent.observability.online_store import FeedbackRating, ReviewRubric

NonBlank = Annotated[str, StringConstraints(pattern=r"\S")]
ThreadPart = Annotated[str, StringConstraints(pattern=r"^[^:\s]+$")]


class ConversationRequest(BaseModel):
    conversation_id: ThreadPart


class SessionRequest(BaseModel):
    customer_id: ThreadPart


class SessionResponse(BaseModel):
    token: str


class ChatRequest(ConversationRequest):
    message: NonBlank


class ResumeRequest(ConversationRequest):
    value: NonBlank


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    milvus: bool
    order_db: bool
    models_configured: bool


CheckName = Literal["postgres", "migrations", "redis", "milvus"]
CheckState = Literal["ok", "down", "disabled"]


class LiveResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadyResponse(BaseModel):
    status: Literal["ok", "down"]
    checks: dict[CheckName, CheckState]


class DeleteMemoriesResponse(BaseModel):
    deleted: int


class AgentClaimRequest(BaseModel):
    agent_id: NonBlank


class AgentReplyRequest(BaseModel):
    agent_id: NonBlank
    message: NonBlank


class AgentResolveRequest(BaseModel):
    agent_id: NonBlank
    label: ResolutionLabel
    note: str = ""
    hand_back_to_ai: bool = True


class FeedbackRequest(BaseModel):
    message_id: NonBlank
    conversation_id: ThreadPart
    rating: FeedbackRating
    reason: str | None = None
    trace_id: str | None = None


class FeedbackResponse(BaseModel):
    id: str
    message_id: str
    rating: FeedbackRating
    created: bool


class ReviewLabelRequest(BaseModel):
    reviewer_id: NonBlank
    rubric_label: ReviewRubric
    note: str = ""
