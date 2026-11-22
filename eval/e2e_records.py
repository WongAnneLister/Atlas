"""Typed records for resumable full-graph evaluation runs."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from eval.schema import EvalItem, MultipartItem
from support_agent.observability.cost import ModelUsage
from support_agent.reliability.events import ReliabilityEvent
from support_agent.reliability.settings import ChaosSettings


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
    code_hash: str | None = None
    prompt_hash: str | None = None
    runtime: dict[str, str] | None = None
    chaos: ChaosSettings | None = None
    endpoint_host: str | None = None
    build_id: str | None = None
    # How items were collected (eval/e2e_speed.py). Older runs were serial and uncached.
    workers: int = Field(default=1, ge=1)
    latency_comparable: bool = True
    rerank_scores: dict[str, Any] | None = None


class E2EPart(BaseModel):
    """Observed outcome for one planned part, including its validated citation sections."""

    text: str = Field(min_length=1)
    intent: str | None = None
    gate: dict[str, Any] | None = None
    retrieved_section_ids: list[str] = Field(default_factory=list)
    retrieved_sources: list[dict[str, str]] = Field(default_factory=list)
    answered: bool = False
    handed_off: bool = False
    cited_section_ids: list[str] = Field(default_factory=list)


class E2ERecord(BaseModel):
    record_type: Literal["item"] = "item"
    build_id: str | None = None
    item: EvalItem | MultipartItem
    intent: str | None = None
    path: str | None = None
    route_source: Literal["whole", "parts"] | None = None
    trace: list[str] = Field(default_factory=list)
    gate: dict[str, Any] | None = None
    parts: list[E2EPart] | None = None
    classification_failed: bool | None = None
    classification_error_type: str | None = None
    retrieval_error_type: str | None = None
    answer_status: str | None = None
    answer_error_type: str | None = None
    coverage: dict[str, Any] | None = None
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
    # Commit 15: per reported model. None in runs recorded before it.
    llm_calls: int | None = Field(default=None, ge=0)
    usage_by_model: dict[str, ModelUsage] | None = None
    reliability_events: list[ReliabilityEvent] = Field(default_factory=list)


class JudgeRecord(BaseModel):
    item_id: str
    flagged: bool
    claims: list[str] = Field(default_factory=list)
    confirmed: Literal["", "yes", "no"] = ""


def load_cached_run(
    path: Path, metadata: E2EMetadata, items: Sequence[EvalItem | MultipartItem]
) -> tuple[E2EMetadata, dict[str, E2ERecord]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    saved = E2EMetadata.model_validate_json(lines[0])
    for key in (
        "config_hash",
        "eval_file_hash",
        "corpus_hash",
        "split",
        "models",
        "dataset_versions",
        "customer_id",
        "threshold",
        "code_hash",
        "prompt_hash",
        "runtime",
        "chaos",
        "endpoint_host",
        "build_id",
    ):
        if getattr(saved, key) != getattr(metadata, key):
            raise ValueError(f"E2E cache changed {key}; choose a fresh output")
    rows = [E2ERecord.model_validate_json(line) for line in lines[1:] if line.strip()]
    records = {r.item.id: r for r in rows}
    if len(records) != len(rows):
        raise ValueError("E2E cache has duplicate items")
    expected = {i.id: i.model_dump() for i in items}
    if any(expected.get(r.item.id) != r.item.model_dump() for r in rows):
        raise ValueError("E2E cache items changed")
    return saved, records
