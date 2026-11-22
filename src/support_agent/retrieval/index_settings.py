"""Configuration for evidence collection and index operations."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from support_agent.reliability.settings import RetrySettings


class RerankCacheSettings(BaseModel):
    """Local store of cross-encoder logits reused by release-evidence runs only."""

    enabled: bool
    path: str = Field(min_length=1)
    # Installed versions of these packages are part of every score's key.
    key_packages: list[str] = Field(min_length=1)


class IndexReleaseSettings(BaseModel):
    sets: list[Literal["dev", "smoke"]] = Field(min_length=1)
    absolute_splits: list[Literal["dev", "test"]] = Field(min_length=1)
    hit_k: int = Field(gt=0)
    retry: RetrySettings
    rerank_cache: RerankCacheSettings

    @field_validator("sets")
    @classmethod
    def unique_sets(cls, values: list[Literal["dev", "smoke"]]) -> list[Literal["dev", "smoke"]]:
        if len(set(values)) != len(values):
            raise ValueError("Release sets must be unique")
        return values


class IndexSettings(BaseModel):
    live_alias: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    collection_prefix: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    builds_directory: str
    preview_directory: str
    integration_prefix: str
    protected_collections: list[str]
    alias_ttl_s: float = Field(gt=0)
    keep_builds: int = Field(gt=0)
    blocked_postgres_ports: list[int]
    release: IndexReleaseSettings
