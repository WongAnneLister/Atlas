"""Configuration models for ContextBuilder, budgets, and provider cache breakpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CacheProvider = Literal["auto", "anthropic", "openai", "deepseek", "none"]
ContextStrategy = Literal["chunked", "sliding", "rolling", "chunked_nocache"]


class NodeBudgetProfile(BaseModel):
    total_tokens: int = Field(default=8192, gt=0)
    history_max_tokens: int = Field(default=2048, ge=0)
    evidence_min_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    share_prefix: bool = True
    recent_turns: int | None = Field(default=None, ge=0)


class CacheAdapterSettings(BaseModel):
    provider: CacheProvider = "auto"
    max_breakpoints: int = Field(default=4, ge=0, le=8)
    min_cacheable_tokens: int = Field(default=1024, ge=0)
    layer_ttls: dict[str, int] = Field(
        default_factory=lambda: {
            "L0_global": 3600,
            "L1_session": 300,
            "L2_compacted": 300,
            "L3_history": 300,
        }
    )


def _default_profiles() -> dict[str, NodeBudgetProfile]:
    return {
        "rewrite": NodeBudgetProfile(total_tokens=4096, history_max_tokens=1600, share_prefix=True),
        "classify": NodeBudgetProfile(
            total_tokens=2048, history_max_tokens=400, share_prefix=False, recent_turns=2
        ),
        "plan": NodeBudgetProfile(total_tokens=2048, history_max_tokens=0, share_prefix=False),
        "input_guard": NodeBudgetProfile(
            total_tokens=1024, history_max_tokens=0, share_prefix=False
        ),
        "answer": NodeBudgetProfile(
            total_tokens=12000,
            history_max_tokens=3000,
            evidence_min_ratio=0.40,
            share_prefix=True,
        ),
        "tools": NodeBudgetProfile(total_tokens=8192, history_max_tokens=2048, share_prefix=True),
        "decide": NodeBudgetProfile(
            total_tokens=8192,
            history_max_tokens=1500,
            evidence_min_ratio=0.35,
            share_prefix=True,
        ),
        "complaint": NodeBudgetProfile(
            total_tokens=4096, history_max_tokens=1024, share_prefix=True
        ),
        "verify": NodeBudgetProfile(
            total_tokens=8192, history_max_tokens=0, evidence_min_ratio=0.50, share_prefix=False
        ),
        "split_claims": NodeBudgetProfile(
            total_tokens=4096, history_max_tokens=0, share_prefix=False
        ),
        "order_extract": NodeBudgetProfile(
            total_tokens=2048, history_max_tokens=0, share_prefix=False
        ),
        "grounding": NodeBudgetProfile(total_tokens=4096, history_max_tokens=0, share_prefix=False),
        "summarise": NodeBudgetProfile(total_tokens=6144, history_max_tokens=0, share_prefix=True),
        "extract_facts": NodeBudgetProfile(
            total_tokens=2048, history_max_tokens=0, share_prefix=False
        ),
    }


class ContextSettings(BaseModel):
    enabled: bool = True
    strategy: ContextStrategy = "chunked"
    sliding_window_turns: int = Field(default=4, ge=1)
    chars_per_token: float = Field(default=3.8, gt=0.0)
    message_overhead_tokens: int = Field(default=4, ge=0)
    hard_history_turn_cap: int = Field(default=16, ge=1)
    cache_read_multiplier: float = Field(default=0.1, ge=0.0, le=1.0)
    cache_write_multiplier: float = Field(default=1.0, ge=0.0, le=5.0)
    cache_adapter: CacheAdapterSettings = Field(default_factory=CacheAdapterSettings)
    profiles: dict[str, NodeBudgetProfile] = Field(default_factory=_default_profiles)

    def profile_for(self, node: str) -> NodeBudgetProfile:
        return self.profiles.get(node, NodeBudgetProfile())
