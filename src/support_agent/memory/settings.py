"""Configuration for short-term and long-term customer memory."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

MemoryKind = Literal["open_issue", "preference", "product_owned", "past_resolution"]
ALL_MEMORY_KINDS: tuple[MemoryKind, ...] = (
    "open_issue",
    "preference",
    "product_owned",
    "past_resolution",
)


class ShortTermMemorySettings(BaseModel):
    enabled: bool = True
    strategy: Literal["chunked", "rolling"] = "chunked"
    pinned_facts_enabled: bool = True
    compaction_enabled: bool = True
    chunk_turns: int = Field(default=6, ge=1)
    history_budget: int = Field(default=1600, gt=0)
    summary_budget: int = Field(default=600, gt=0)
    low_watermark: float = Field(default=0.6, gt=0.0, lt=1.0)
    summariser_role: Literal["fast", "main"] = "fast"
    llm_fact_extraction: bool = False


def _default_ttl_days() -> dict[MemoryKind, int]:
    return {
        "open_issue": 30,
        "preference": 365,
        "product_owned": 365,
        "past_resolution": 90,
    }


class LongTermMemorySettings(BaseModel):
    enabled: bool = False
    allowed_kinds: list[MemoryKind] = Field(default_factory=lambda: list(ALL_MEMORY_KINDS))
    ttl_days: dict[MemoryKind, int] = Field(default_factory=_default_ttl_days)
    min_confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    max_content_chars: int = Field(default=240, ge=20, le=2000)
    min_content_chars: int = Field(default=6, ge=1, le=200)
    max_memories_per_customer: int = Field(default=50, ge=1)
    session_top_k: int = Field(default=5, ge=1)
    session_budget_tokens: int = Field(default=300, gt=0)
    mid_turn_top_k: int = Field(default=2, ge=1)
    mid_turn_min_relevance: float = Field(default=0.35, ge=0.0, le=1.0)
    dedupe_similarity_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    supersede_similarity_threshold: float = Field(default=0.45, ge=0.0, le=1.0)
    extractor_role: Literal["fast", "main"] = "fast"
    extract_on_handoff: bool = True
    extract_on_end: bool = True
    sqlite_path: str = "data/processed/memories.sqlite"
