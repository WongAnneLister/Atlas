"""Typed cache records and the provenance of one retrieval experiment."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from eval.schema import EvalItem
from support_agent.retrieval.types import RetrievedChunk


class SearchRecord(BaseModel):
    item: EvalItem
    mode: str
    chunks: list[RetrievedChunk]
    latency_s: float = Field(ge=0)
    components_s: dict[str, float]
    provenance: str
    cache_hit: bool = False


class RunMetadata(BaseModel):
    git_sha: str
    code_hash: str
    config_hash: str
    eval_file_hash: str
    frozen_set_hash: str
    corpus_hash: str
    date: str
    dataset_versions: dict[str, str]
    models: dict[str, str]
    settings: dict[str, Any]
    reviewed: int
    total_items: int
    index_identities: dict[str, str]
    runtime: dict[str, str] = Field(default_factory=dict)
    variant_config_hashes: dict[str, str] = Field(default_factory=dict)


class RetrievalRun(BaseModel):
    metadata: RunMetadata
    requested_split: Literal["dev", "test", "all"]
    records: list[SearchRecord]
