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
    embedding_dim: int
    reranker_model: str
    dense_top_k: int
    bm25_top_k: int
    rrf_k: int
    rerank_top_k: int


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


class MilvusSettings(BaseModel):
    uri: str
    collection: str


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
    gate: GateSettings
    agent: AgentSettings
    intent: IntentSettings
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
