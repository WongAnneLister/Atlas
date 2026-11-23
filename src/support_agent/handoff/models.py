"""Typed models for the human handoff queue and labelled resolutions."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from support_agent.handoff.settings import HandoffPriority

HandoffStatus = Literal["open", "claimed", "resolved"]
ResolutionLabel = Literal[
    "kb_gap",
    "retrieval_miss",
    "gate_too_strict",
    "correct_handoff",
    "policy_exception",
    "abuse",
]
ALL_RESOLUTION_LABELS: tuple[ResolutionLabel, ...] = (
    "kb_gap",
    "retrieval_miss",
    "gate_too_strict",
    "correct_handoff",
    "policy_exception",
    "abuse",
)


class HumanThreadMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    sender: Literal["customer", "agent"]
    author: str
    text: str
    created_at: datetime


class HandoffItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    conversation_id: str
    customer_id: str
    reason: str
    priority: HandoffPriority
    status: HandoffStatus
    claimed_by: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    claimed_at: datetime | None = None
    resolved_at: datetime | None = None
    resolution_label: ResolutionLabel | None = None
    resolution_note: str | None = None
    idempotency_key: str | None = None
    hand_back_to_ai: bool = True

    @property
    def human_thread(self) -> list[dict[str, Any]]:
        raw = self.payload.get("human_thread", [])
        return list(raw) if isinstance(raw, list) else []
