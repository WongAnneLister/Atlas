"""Configuration for cache-friendly short-term memory."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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
