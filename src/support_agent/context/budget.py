"""Token counter interface, budget breakdown records, and overflow exception."""

from __future__ import annotations

import math
from typing import Protocol

from langchain_core.messages import BaseMessage
from pydantic import BaseModel, ConfigDict, Field

from support_agent.context.sections import LAYER_ORDER, StabilityLayer


class ContextOverflow(Exception):
    """Raised when never-trim sections alone exceed the node's total token budget."""

    def __init__(self, node: str, required_tokens: int, budget_tokens: int) -> None:
        self.node = node
        self.required_tokens = required_tokens
        self.budget_tokens = budget_tokens
        super().__init__(
            f"Context overflow in {node}: required {required_tokens} > budget {budget_tokens}"
        )


class TokenCounter(Protocol):
    def count_text(self, text: str) -> int: ...
    def count_message(self, message: BaseMessage) -> int: ...


class ApproxTokenCounter:
    """Calibrated deterministic token estimator (chars / ratio + per-message overhead)."""

    def __init__(self, *, chars_per_token: float = 3.8, message_overhead: int = 4) -> None:
        if chars_per_token <= 0:
            raise ValueError("chars_per_token must be positive")
        self.chars_per_token = chars_per_token
        self.message_overhead = message_overhead

    def count_text(self, text: str) -> int:
        if not text:
            return 0
        return max(1, math.ceil(len(text) / self.chars_per_token))

    def count_message(self, message: BaseMessage) -> int:
        content = message.content
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            parts = [
                item.get("text", "") if isinstance(item, dict) else str(item) for item in content
            ]
            text = "\n".join(parts)
        else:
            text = str(content)
        return self.message_overhead + self.count_text(text)


class DroppedItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    section: str
    reason: str
    tokens_dropped: int = Field(ge=0)


class ContextBreakdown(BaseModel):
    model_config = ConfigDict(frozen=True)

    node: str
    total_tokens: int = Field(ge=0)
    budget_tokens: int = Field(gt=0)
    by_layer: dict[StabilityLayer, int] = Field(
        default_factory=lambda: dict.fromkeys(LAYER_ORDER, 0)
    )
    by_section: dict[str, int] = Field(default_factory=dict)
    dropped: list[DroppedItem] = Field(default_factory=list)
    prefix_hash: str
    l0_hash: str
    history_capped: bool = False
