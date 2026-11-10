"""Typed records for resumable full-graph evaluation runs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from eval.schema import EvalItem


class E2EMetadata(BaseModel):
    record_type: Literal["metadata"] = "metadata"
    git_sha: str
    config_hash: str
    eval_file_hash: str
    corpus_hash: str
    models: dict[str, str]
    dataset_versions: dict[str, str]
    split: Literal["dev", "test", "all"]
    date: str
    customer_id: str
    threshold: float


class E2ERecord(BaseModel):
    record_type: Literal["item"] = "item"
    item: EvalItem
    intent: str | None = None
    path: str | None = None
    trace: list[str] = Field(default_factory=list)
    gate: dict[str, Any] | None = None
    answer: str = ""
    citations: list[dict[str, Any]] = Field(default_factory=list)
    cited_sources: list[dict[str, str]] = Field(default_factory=list)
    retrieved_section_ids: list[str] = Field(default_factory=list)
    handoff_reason: str | None = None
    accepted: bool = False
    latency_first_token_s: float | None = Field(default=None, ge=0)
    latency_full_answer_s: float = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)


class JudgeRecord(BaseModel):
    item_id: str
    flagged: bool
    claims: list[str] = Field(default_factory=list)
    confirmed: Literal["", "yes", "no"] = ""
