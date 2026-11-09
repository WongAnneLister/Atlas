"""Typed settings loaded from `configs/default.yaml`, overridable by env vars.

Priority (high to low): init kwargs, env vars (`SUPPORT_AGENT__SECTION__KEY`), YAML file.
The YAML path can be changed with `SUPPORT_AGENT_CONFIG`.
"""

from __future__ import annotations

import math
import os
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "configs" / "default.yaml"
CONFIG_PATH_ENV = "SUPPORT_AGENT_CONFIG"


class DataSource(BaseModel):
    name: str
    repo_id: str
    revision: str
    role: str
    files: list[str]
    third_party_note: str | None = None


class DocsSettings(BaseModel):
    near_duplicate_threshold: float = Field(ge=0, le=1)
    minimum_coverage: float = Field(ge=0, le=1)
    classify_leftovers: bool
    model_pattern: str
    product_categories: dict[str, str]
    topic_rules: dict[str, str]


class DataSettings(BaseModel):
    raw_dir: str
    processed_dir: str
    docs: DocsSettings
    sources: list[DataSource]


class LLMSettings(BaseModel):
    provider: str | None
    fast_model: str | None
    main_model: str | None
    temperature: float
    timeout_s: float


class RetrievalSettings(BaseModel):
    embedding_model: str
    embedding_revision: str
    embedding_dim: int = Field(gt=0)
    embedding_cache_dir: str
    embedding_device: str
    embedding_batch_size: int = Field(gt=0)
    embedding_normalize: bool
    embedding_use_fp16: bool
    embedding_cpu_threads: int = Field(gt=0)
    embedding_max_tokens: int = Field(gt=2)
    embedding_window_tokens: int = Field(gt=2)
    reranker_model: str
    reranker_revision: str
    reranker_cache_dir: str
    reranker_device: str
    reranker_use_fp16: bool
    reranker_batch_size: int = Field(gt=0)
    reranker_max_tokens: int = Field(gt=0)
    reranker_cpu_threads: int = Field(gt=0)
    rerank_candidates_k: int = Field(gt=0)
    dense_top_k: int = Field(gt=0)
    bm25_top_k: int = Field(gt=0)
    search_top_k: int = Field(gt=0)
    bm25_normalise_model_numbers: bool
    rrf_k: int = Field(ge=0)
    rerank_top_k: int = Field(gt=0)

    @model_validator(mode="after")
    def _valid_embedding_window(self) -> RetrievalSettings:
        if self.embedding_window_tokens > self.embedding_max_tokens:
            raise ValueError("embedding_window_tokens exceeds model context limit")
        if self.rerank_top_k > self.rerank_candidates_k:
            raise ValueError("rerank_top_k exceeds rerank_candidates_k")
        return self


class RetrievalEvalSettings(BaseModel):
    metric_ks: list[int]
    target_recall_at_5: float = Field(ge=0, le=1)
    cache_dir: str
    heading_ablation_collection: str
    baseline_collection: str
    run_ablations: bool
    local_chunk_text: bool

    @model_validator(mode="after")
    def _positive_cutoffs(self) -> RetrievalEvalSettings:
        if not {1, 3, 5}.issubset(self.metric_ks) or any(k <= 0 for k in self.metric_ks):
            raise ValueError("metric_ks must include the positive PRD cutoffs 1, 3 and 5")
        if self.baseline_collection == self.heading_ablation_collection:
            raise ValueError("Experiment collections must be distinct")
        return self


class ChunkSettings(BaseModel):
    max_tokens: int = Field(gt=0)
    overlap_tokens: int = Field(ge=0)
    prepend_heading: bool

    @model_validator(mode="after")
    def _valid_overlap(self) -> ChunkSettings:
        if self.overlap_tokens >= self.max_tokens:
            raise ValueError("chunk.overlap_tokens must be smaller than max_tokens")
        return self


class GateWeights(BaseModel):
    top_score: float
    good_count: float
    margin: float
    key_hit: float


class GateSettings(BaseModel):
    weights: GateWeights
    good_evidence_min: float
    good_count_cap: int
    threshold: float | None

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> GateSettings:
        total = sum(self.weights.model_dump().values())
        if not math.isclose(total, 1.0):
            raise ValueError(f"gate.weights must sum to 1.0, got {total}")
        return self


class AgentSettings(BaseModel):
    max_steps: int


class IntentSettings(BaseModel):
    min_confidence: float


class EvalSettings(BaseModel):
    sets_dir: str
    seed: int
    per_group: int = Field(gt=0)
    dev_per_group: int = Field(gt=0)
    phrase_overlap: float = Field(gt=0, le=1)
    near_duplicate_threshold: float = Field(gt=0, le=1)
    token_duplicate_threshold: float = Field(gt=0, le=1)
    split_search_attempts: int = Field(gt=0)
    max_model_attributes: int = Field(gt=0)
    cross_doc_candidates: int = Field(gt=0)
    draft_mode: Literal["template", "fast"]
    no_answer_drafts: str
    policy_topics: list[str]
    faq_categories: list[str]

    @model_validator(mode="after")
    def _valid_split(self) -> EvalSettings:
        if self.dev_per_group >= self.per_group:
            raise ValueError("evaluation.dev_per_group must be smaller than per_group")
        return self


class MilvusSettings(BaseModel):
    uri: str
    collection: str
    timeout_s: float = Field(gt=0)
    upsert_batch_size: int = Field(gt=0)
    query_batch_size: int = Field(gt=0)
    id_max_bytes: int = Field(gt=0)
    section_max_bytes: int = Field(gt=0)
    heading_max_bytes: int = Field(gt=0)
    text_max_bytes: int = Field(gt=0, le=65535)
    hnsw_m: int = Field(gt=0)
    hnsw_ef_construction: int = Field(gt=0)
    hnsw_ef_search: int = Field(gt=0)
    sparse_algorithm: str
    bm25_k1: float = Field(gt=0)
    bm25_b: float = Field(ge=0, le=1)
    analyzer: dict[str, object]


class SeedProduct(BaseModel):
    product_id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: str = Field(min_length=1)


class OrdersSettings(BaseModel):
    db_path: str
    seed: int
    n_orders: int = Field(gt=0)
    n_customers: int = Field(gt=0)
    today: date
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    recent_limit: int = Field(gt=0)
    min_items: int = Field(gt=0)
    max_items: int = Field(gt=0)
    max_quantity: int = Field(gt=0)
    min_unit_price_cents: int = Field(gt=0)
    max_unit_price_cents: int = Field(gt=0)
    max_order_age_days: int = Field(gt=0)
    delivery_ages_days: list[int] = Field(min_length=1)
    shipping_lead_days: int = Field(gt=0)
    transit_age_days: int = Field(gt=0)
    tracking_delay_days: int = Field(gt=0)
    coupon_probability: float = Field(ge=0, le=1)
    final_sale_probability: float = Field(ge=0, le=1)
    coupon_code: str = Field(min_length=1)
    coupon_discount: Decimal = Field(ge=0, lt=1)
    fallback_products: list[SeedProduct] = Field(min_length=1)

    @model_validator(mode="after")
    def _valid_seed_ranges(self) -> OrdersSettings:
        if self.min_items > self.max_items:
            raise ValueError("orders.min_items exceeds max_items")
        if self.min_unit_price_cents > self.max_unit_price_cents:
            raise ValueError("orders.min_unit_price_cents exceeds max_unit_price_cents")
        if any(age < 0 for age in self.delivery_ages_days):
            raise ValueError("orders.delivery_ages_days must be nonnegative")
        return self


class MemorySettings(BaseModel):
    recent_turns: int
    summary_max_tokens: int


class TracingSettings(BaseModel):
    enabled: bool


class APISettings(BaseModel):
    host: str
    port: int


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SUPPORT_AGENT__",
        env_nested_delimiter="__",
        extra="ignore",
    )

    data: DataSettings
    llm: LLMSettings
    retrieval: RetrievalSettings
    retrieval_eval: RetrievalEvalSettings
    chunk: ChunkSettings
    gate: GateSettings
    agent: AgentSettings
    intent: IntentSettings
    evaluation: EvalSettings
    milvus: MilvusSettings
    orders: OrdersSettings
    memory: MemorySettings
    tracing: TracingSettings
    api: APISettings

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        yaml_source = YamlConfigSettingsSource(settings_cls, yaml_file=config_path())
        return (init_settings, env_settings, yaml_source)


def config_path() -> Path:
    """Return the YAML config path (env override or the repo default)."""
    return Path(os.environ.get(CONFIG_PATH_ENV, DEFAULT_CONFIG_PATH))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once per process. Call `get_settings.cache_clear()` in tests."""
    return Settings()
