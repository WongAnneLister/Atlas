"""Configuration models for the versioned three-layer cache."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EmbeddingCacheSettings(BaseModel):
    enabled: bool = True
    ttl_s: int = Field(default=604800, gt=0)


class RetrievalCacheSettings(BaseModel):
    enabled: bool = True
    ttl_s: int = Field(default=86400, gt=0)


class NearDuplicateSettings(BaseModel):
    """Optional semantic answer-cache matching, gated behind an explicit flag."""

    enabled: bool = False
    similarity_threshold: float = Field(default=0.97, ge=0.0, le=1.0)
    max_entries_per_bucket: int = Field(default=64, gt=0)


class AnswerCacheSettings(BaseModel):
    enabled: bool = True
    ttl_s: int = Field(default=3600, gt=0)
    recent_turns: int = Field(default=6, ge=0)
    near_duplicate: NearDuplicateSettings = Field(default_factory=NearDuplicateSettings)


class CacheSettings(BaseModel):
    enabled: bool = True
    key_prefix: str = Field(default="atlas:cache:v1", min_length=1)
    index_revision_ttl_s: int = Field(default=2592000, gt=0)
    embedding: EmbeddingCacheSettings = Field(default_factory=EmbeddingCacheSettings)
    retrieval: RetrievalCacheSettings = Field(default_factory=RetrievalCacheSettings)
    answer: AnswerCacheSettings = Field(default_factory=AnswerCacheSettings)
