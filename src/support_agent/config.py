"""Typed settings loaded from `configs/default.yaml`, overridable by env vars.

Priority (high to low): init kwargs, env vars (`SUPPORT_AGENT__SECTION__KEY`), YAML file.
The YAML path can be changed with `SUPPORT_AGENT_CONFIG`.
"""

from __future__ import annotations

import math
import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "configs" / "default.yaml"
CONFIG_PATH_ENV = "SUPPORT_AGENT_CONFIG"


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


class OrdersSettings(BaseModel):
    db_path: str
    seed: int
    n_orders: int


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
