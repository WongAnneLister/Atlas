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
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import (
    BaseSettings,
    InitSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from support_agent.cache.settings import CacheSettings
from support_agent.config_layers import yaml_layers
from support_agent.context.settings import ContextSettings
from support_agent.db.settings import DatabaseSettings
from support_agent.graph.settings import (
    GraphSettings,
    IntentEvalSettings,
    IntentSettings,
    KnowledgeSettings,
    PlanningSettings,
)
from support_agent.guardrails.settings import GuardrailSettings
from support_agent.handoff.settings import HandoffSettings
from support_agent.infra.settings import ReadinessSettings, RedisSettings
from support_agent.memory.settings import LongTermMemorySettings, ShortTermMemorySettings
from support_agent.reliability.settings import (
    ChaosSettings,
    FallbackSettings,
    ReliabilitySettings,
    validate_reliability,
)
from support_agent.retrieval.index_settings import IndexSettings

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
    timeout_s: float = Field(gt=0, allow_inf_nan=False)
    fallbacks: FallbackSettings = Field(default_factory=FallbackSettings)
    provider_max_retries: int = Field(default=0, ge=0)
    model_kwargs: dict[str, Any] = Field(default_factory=dict)


class StoreSettings(BaseModel):
    # Case-insensitive regex that marks a question as asking about this store.
    query_pattern: str = Field(min_length=1)
    # Substring of a section id that marks the section as this store's document.
    section_marker: str = Field(min_length=1)


class StoreScopeSettings(BaseModel):
    """Keep other stores' sections out of the evidence for a single-store question."""

    enabled: bool = False
    # Reranked results considered before filtering; the gate still sees rerank_top_k.
    pool_k: int = Field(default=10, gt=0)
    stores: dict[str, StoreSettings] = Field(default_factory=dict)


class RetrievalFilterSettings(BaseModel):
    enabled: bool = False
    category: bool = False
    category_terms: dict[str, list[str]] = Field(default_factory=dict)


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
    # Drop a reranked chunk whose text repeats a higher-ranked one (same FAQ filed twice).
    dedupe_text: bool = False
    store_scope: StoreScopeSettings = Field(default_factory=StoreScopeSettings)
    filters: RetrievalFilterSettings = Field(default_factory=RetrievalFilterSettings)

    @model_validator(mode="after")
    def _valid_embedding_window(self) -> RetrievalSettings:
        if self.embedding_window_tokens > self.embedding_max_tokens:
            raise ValueError("embedding_window_tokens exceeds model context limit")
        if self.rerank_top_k > self.rerank_candidates_k:
            raise ValueError("rerank_top_k exceeds rerank_candidates_k")
        if self.store_scope.pool_k > self.rerank_candidates_k:
            raise ValueError("store_scope.pool_k exceeds rerank_candidates_k")
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
    # "token": fixed token windows inside each section, whole product manuals.
    # "faq_unit": one FAQ question and answer per chunk, product manuals in windows.
    strategy: Literal["token", "faq_unit"] = "token"
    product_window_tokens: int = Field(default=400, gt=0)
    product_overlap_tokens: int = Field(default=50, ge=0)
    # Start every manual window with the product heading, so the reranker and the gate
    # see which product a deep window belongs to.
    product_window_header: bool = False

    @model_validator(mode="after")
    def _valid_overlap(self) -> ChunkSettings:
        if self.overlap_tokens >= self.max_tokens:
            raise ValueError("chunk.overlap_tokens must be smaller than max_tokens")
        if self.product_overlap_tokens >= self.product_window_tokens:
            raise ValueError("chunk.product_overlap_tokens must be smaller than the window")
        return self


class GateWeights(BaseModel):
    top_score: float = Field(ge=0, le=1)
    good_count: float = Field(ge=0, le=1)
    margin: float = Field(ge=0, le=1)
    key_hit: float = Field(ge=0, le=1)


class GateSettings(BaseModel):
    weights: GateWeights
    good_evidence_min: float = Field(ge=0, le=1)
    good_count_cap: int = Field(gt=0)
    policy_nouns: list[str] = Field(min_length=1)
    untuned_threshold: float = Field(ge=0, le=1)
    threshold: float | None = Field(default=None, ge=0, le=1)
    # "neutral" scores key_hit 1.0 without key terms; "exclude" drops it and renormalises.
    key_hit_without_terms: Literal["neutral", "exclude"] = "neutral"
    # Capitalised names in the query (e.g. "Cash App Pay") count as key terms.
    entity_terms: bool = False
    # Fail when the query names models or entities and none appear in the top chunks.
    require_specific_term_hit: bool = False
    # Fail when the query names model numbers and none is in the top chunks; other
    # names (e.g. "USB") do not count, unlike require_specific_term_hit.
    require_model_number_hit: bool = False
    key_hit_top_chunks: int = Field(default=3, gt=0)
    # Store names that scope a question rather than name the asked-about thing.
    scope_terms: list[str] = Field(default_factory=list)
    # Capitalised words that are not names (question words, pronouns, fillers).
    entity_stopwords: list[str] = Field(default_factory=list)
    # "lowest": first zero-dev-false-accept threshold; "midpoint": centre of the dev gap.
    threshold_rule: Literal["lowest", "midpoint"] = "lowest"

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> GateSettings:
        total = sum(self.weights.model_dump().values())
        if not math.isclose(total, 1.0):
            raise ValueError(f"gate.weights must sum to 1.0, got {total}")
        return self


class AgentSettings(BaseModel):
    max_steps: int = Field(gt=0)
    max_consecutive_tool_errors: int = Field(gt=0)
    max_tool_calls_per_step: int = Field(gt=0)
    trace_max_chars: int = Field(gt=0)
    complaint_max_sentences: int = Field(gt=0, le=2)
    # When the order model calls no tool, the question is not an order lookup:
    # send it to the gated knowledge path instead of handing off.
    knowledge_fallback: bool = False
    # Every factual claim in an order-tool answer must quote this turn's tool data;
    # otherwise the free text is dropped and the gated knowledge path answers.
    order_grounding: bool = False
    # "template": the order model only picks lookups and decides whether the order data
    # answers the question; code renders the reply. "free_text": the model writes it.
    order_replies: Literal["free_text", "template"] = "free_text"
    # Tries per grounding check; only a reply without a valid structured call is retried.
    grounding_attempts: int = Field(default=1, ge=1)


class RefundSettings(BaseModel):
    # "order_fields": the original query built from intent, item categories and status.
    # "store_faq": one FAQ-style policy question for the store that sells the mock
    # orders, picked from the order facts. See eval/reports/refund_policy.md.
    policy_query: Literal["order_fields", "store_faq"] = "order_fields"
    # Store (a key of retrieval.store_scope.stores) whose policy governs the mock orders.
    policy_store: str = "generic"
    # How the query names that store; it must match the store's query_pattern.
    store_label: str = "generic store"
    # "v1": refund_decide.md with a bare schema. "v2": refund_decide_v2.md plus schema
    # field descriptions that ask for a [n] marker in every reason and exact item ids.
    # "v3": the v2 schema with refund_decide_v3.md (purchase-date windows, no "no"
    # without a rule that excludes the order). See eval/reports/refund_decisions.md.
    decision_version: Literal["v1", "v2", "v3"] = "v1"


class EvalStatsSettings(BaseModel):
    n_resamples: int = Field(gt=0)
    seed: int = Field(ge=0)
    alpha: float = Field(gt=0, lt=1)


class E2ESpeedSettings(BaseModel):
    """Evaluator speed-ups that must not change a measured value."""

    rerank_cache: bool
    max_workers: int = Field(gt=0)


class ClaimSamplingSettings(BaseModel):
    seed: int = Field(ge=0)
    dev_target: int = Field(gt=0)
    test_target: int = Field(gt=0)
    synthetic_per_split: int = Field(gt=0)
    foreign_min_words: int = Field(ge=6)
    uncited_cap_divisor: int = Field(ge=3)
    min_duration: int = Field(ge=0)
    min_amount: int = Field(ge=0)
    max_per_item: int = Field(gt=0)


class GroundingSettings(BaseModel):
    enabled: bool
    split_compound: bool
    verifier_role: Literal["fast", "main"]
    generic_phrases: list[str] = Field(max_length=9)
    short_sentence_words: int = Field(ge=0)
    target_recall: float = Field(gt=0, le=1)


def _default_grounding() -> GroundingSettings:
    config = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    return GroundingSettings.model_validate(config["grounding"])


class SimSettings(BaseModel):
    model_role: Literal["fast", "main"] = "fast"
    model: str | None = None
    temperature: float = Field(default=0.4, ge=0.0, le=2.0)
    seed: int = Field(default=27, ge=0)
    repeats: int = Field(default=3, ge=1)
    nightly_subset_size: int = Field(default=10, ge=1)
    loop_threshold: int = Field(default=3, ge=2)
    validity_sample_size: int = Field(default=10, ge=1)


class EvalPlatformSettings(BaseModel):
    stats: EvalStatsSettings
    multipart_min_overlap: float = Field(gt=0, le=1)
    e2e_speed: E2ESpeedSettings
    claims: ClaimSamplingSettings
    sim: SimSettings = Field(default_factory=SimSettings)


def _default_eval_platform() -> EvalPlatformSettings:
    config = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    return EvalPlatformSettings.model_validate(config["eval"])


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
    customer_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def _valid_split(self) -> EvalSettings:
        if self.dev_per_group >= self.per_group:
            raise ValueError("evaluation.dev_per_group must be smaller than per_group")
        return self


class MilvusSettings(BaseModel):
    uri: str
    collection: str
    timeout_s: float = Field(gt=0, allow_inf_nan=False)
    upsert_batch_size: int = Field(gt=0)
    query_batch_size: int = Field(gt=0)
    id_max_bytes: int = Field(gt=0)
    section_max_bytes: int = Field(gt=0)
    heading_max_bytes: int = Field(gt=0)
    text_max_bytes: int = Field(gt=0, le=65535)
    metadata_max_bytes: int = Field(gt=0, le=65535)
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


class PolicyVersionSettings(BaseModel):
    enabled: bool
    default_effective_from: date
    open_end_day: int
    spec_path: str


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
    short_term: ShortTermMemorySettings = Field(default_factory=ShortTermMemorySettings)
    long_term: LongTermMemorySettings = Field(default_factory=LongTermMemorySettings)


class TracingSettings(BaseModel):
    enabled: bool
    # Replace customer text with a placeholder before it leaves the process.
    redact_inputs: bool = False
    # Chunks kept (id + scores only) when a span carries retrieval results.
    max_chunks: int = Field(default=5, gt=0)


class ModelPrice(BaseModel):
    input_per_million_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    output_per_million_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    # Date the price was read from the provider's price page; null means "update me".
    checked: date | None = None


class CostSettings(BaseModel):
    # Keyed by the model name the provider reports in its responses.
    prices: dict[str, ModelPrice] = Field(default_factory=dict)


class SessionSettings(BaseModel):
    ttl_s: int = Field(gt=0)


class RateLimitSettings(BaseModel):
    window_s: int = Field(gt=0)
    per_customer: int = Field(gt=0)
    per_ip: int = Field(gt=0)


class APISettings(BaseModel):
    host: str
    port: int
    token_chunk_words: int = Field(gt=0)
    demo_customer_limit: int = Field(gt=0)
    max_message_chars: int = Field(gt=0)
    max_resume_chars: int = Field(gt=0)
    max_body_bytes: int = Field(gt=0)
    session: SessionSettings
    rate_limit: RateLimitSettings
    health_timeout_s: float = Field(gt=0, allow_inf_nan=False)
    warmup_retriever: bool


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SUPPORT_AGENT__",
        env_nested_delimiter="__",
        extra="ignore",
        hide_input_in_errors=True,
    )

    data: DataSettings
    llm: LLMSettings
    retrieval: RetrievalSettings
    retrieval_eval: RetrievalEvalSettings
    chunk: ChunkSettings
    gate: GateSettings
    agent: AgentSettings
    intent: IntentSettings
    graph: GraphSettings
    planning: PlanningSettings
    knowledge: KnowledgeSettings
    grounding: GroundingSettings = Field(default_factory=_default_grounding)
    intent_eval: IntentEvalSettings
    evaluation: EvalSettings
    eval: EvalPlatformSettings = Field(default_factory=_default_eval_platform)
    milvus: MilvusSettings
    index: IndexSettings
    orders: OrdersSettings
    policy_versions: PolicyVersionSettings
    refund: RefundSettings = Field(default_factory=RefundSettings)
    memory: MemorySettings
    context: ContextSettings = Field(default_factory=ContextSettings)
    tracing: TracingSettings
    costs: CostSettings
    api: APISettings
    guardrails: GuardrailSettings
    environment: Literal["local", "dev", "prod"]
    db: DatabaseSettings
    redis: RedisSettings
    cache: CacheSettings = Field(default_factory=CacheSettings)
    readiness: ReadinessSettings
    reliability: ReliabilitySettings
    chaos: ChaosSettings
    handoff: HandoffSettings = Field(default_factory=HandoffSettings)
    database_url: SecretStr | None = Field(default=None, exclude=True)
    redis_url: SecretStr | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def _production_state(self) -> Settings:
        if self.environment == "prod":
            if self.chaos.enabled:
                raise ValueError("prod forbids chaos")
            if self.graph.checkpoint_backend != "postgres":
                raise ValueError("prod requires postgres checkpoints")
            if not self.database_url or not self.database_url.get_secret_value():
                raise ValueError("prod requires DATABASE_URL")
            if self.redis.backend == "null":
                raise ValueError("prod requires Redis")
        validate_reliability(self)
        return self

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        environment = os.getenv("ENV", "local")
        platform = InitSettingsSource(
            settings_cls,
            {
                "environment": environment,
                "database_url": os.getenv("DATABASE_URL") or None,
                "redis_url": os.getenv("REDIS_URL") or None,
            },
        )
        base = yaml_layers(config_path(), DEFAULT_CONFIG_PATH.parent, environment)
        fallbacks: dict[str, list[str]] = {}
        for role in ("fast", "main"):
            value = os.getenv(f"LLM_{role.upper()}_FALLBACKS")
            if value is not None:
                fallbacks[role] = [name for item in value.split(",") if (name := item.strip())]
        dedicated_llm_env = InitSettingsSource(settings_cls, {"llm": {"fallbacks": fallbacks}})
        return (
            platform,
            dedicated_llm_env,
            init_settings,
            env_settings,
            InitSettingsSource(settings_cls, base),
        )


def config_path() -> Path:
    """Return the YAML config path (env override or the repo default)."""
    return Path(os.environ.get(CONFIG_PATH_ENV, DEFAULT_CONFIG_PATH))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once per process. Call `get_settings.cache_clear()` in tests."""
    return Settings()
