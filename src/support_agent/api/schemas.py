"""Public API payloads."""

from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints

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
