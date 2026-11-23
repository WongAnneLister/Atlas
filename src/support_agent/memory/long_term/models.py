"""Typed models for long-term customer memory records and write decisions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from support_agent.memory.settings import MemoryKind


class CustomerMemory(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    customer_id: str
    kind: MemoryKind
    content: str
    structured: dict[str, Any] = Field(default_factory=dict)
    embedding: list[float] | None = None
    idempotency_key: str | None = None
    source_conversation_id: str
    source_turn: int = Field(ge=0)
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    confidence: float = Field(ge=0.0, le=1.0)
    superseded_by: str | None = None
    deleted_at: datetime | None = None


class MemoryCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: str
    content: str
    structured: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    source_turn: int = Field(default=1, ge=0)


class WriteDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    accepted: bool
    action: str  # "insert" | "refresh" | "supersede" | "reject"
    reason: str
    redacted_content: str = ""
    redacted_structured: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None
    target_memory_id: str | None = None


class PublicMemoryItem(BaseModel):
    """Customer-visible representation returned by GET /api/me/memories."""

    model_config = ConfigDict(frozen=True)

    id: str
    kind: MemoryKind
    content: str
    created_at: datetime
    expires_at: datetime


class MemoryStorageStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    active_count: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
