"""Validated intent benchmark inputs and measured prediction records."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from support_agent.graph.intents import Intent


class IntentItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    intent: Intent
    source: str = Field(min_length=1)
    source_label: str = Field(min_length=1)
    split: Literal["intent_holdout"] = "intent_holdout"
    reviewed: bool = False


class ExtraDrafts(BaseModel):
    greetings: list[str]
    returns: list[str]
    returns_source: str
    returns_model: str | None = None


class IntentRecord(BaseModel):
    item: IntentItem
    predicted: Intent
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    parse_failed: bool
    error_type: str | None = None
    model_name: str | None = None
    latency_s: float = Field(ge=0)
    provenance: str
    cache_hit: bool = False


class IntentRun(BaseModel):
    metadata: dict[str, Any]
    records: list[IntentRecord]
