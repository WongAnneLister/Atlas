"""Configuration for the human handoff queue, priorities, and agent console."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

HandoffPriority = Literal["high", "normal", "low"]


def _default_priorities() -> dict[str, HandoffPriority]:
    return {
        "complaint": "high",
        "guardrail_blocked": "high",
        "low_evidence": "normal",
        "low_grounding": "normal",
        "incomplete_evidence": "normal",
        "unsupported_part": "normal",
        "policy_requires_human": "normal",
        "user_requested": "normal",
        "default": "normal",
    }


class HandoffSettings(BaseModel):
    queue_enabled: bool = False
    human_mode_enabled: bool = False
    priorities: dict[str, HandoffPriority] = Field(default_factory=_default_priorities)
    sqlite_path: str = "data/processed/handoffs.sqlite"
    demo_agent_token: str = "atlas-demo-agent"
    human_mode_ack: str = (
        "Your message has been added to your active support ticket. "
        "A human agent will reply shortly."
    )

    def priority_for(self, reason: str) -> HandoffPriority:
        return self.priorities.get(reason, self.priorities.get("default", "normal"))
