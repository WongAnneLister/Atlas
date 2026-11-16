"""Public API payloads."""

from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints

NonBlank = Annotated[str, StringConstraints(pattern=r"\S")]
ThreadPart = Annotated[str, StringConstraints(pattern=r"^[^:\s]+$")]


class ConversationRequest(BaseModel):
    conversation_id: ThreadPart
    customer_id: ThreadPart


class ChatRequest(ConversationRequest):
    message: NonBlank


class ResumeRequest(ConversationRequest):
    value: NonBlank


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    milvus: bool
    order_db: bool
    models_configured: bool
