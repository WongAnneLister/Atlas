"""Typed records shared by lifecycle orchestration and the registry."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, JsonValue

from support_agent.data.section_metadata import SectionMetadata

BuildMode = Literal["full", "incremental", "adopted"]
BuildStatus = Literal["building", "built", "failed", "released", "retired", "dropped"]


def now() -> datetime:
    return datetime.now(UTC)


class SourceDocument(BaseModel):
    doc_id: str
    title: str
    source: list[str]


class SourceSection(BaseModel):
    section_id: str
    doc_id: str
    heading: str
    text: str
    content_hash: str
    metadata: SectionMetadata


class Corpus(BaseModel):
    documents: dict[str, SourceDocument]
    sections: dict[str, SourceSection]
    docs_hash: str


class BuildRecord(BaseModel):
    build_id: str = Field(pattern=r"^[a-f0-9]+$")
    collection: str
    mode: BuildMode
    fingerprint: str
    embed_model: str
    embed_revision: str
    embedding_profile: dict[str, JsonValue] = Field(default_factory=dict)
    chunker_version: str
    docs_hash: str
    parent_build_id: str | None = None
    status: BuildStatus = "building"
    eval_run_id: str | None = None
    override_reason: str | None = None
    created_at: datetime = Field(default_factory=now)
    released_at: datetime | None = None


class BuildSection(BaseModel):
    section_id: str
    section_version: int
    content_hash: str
    chunk_count: int


class AliasRecord(BaseModel):
    alias: str
    build_id: str | None = None
    previous_build_id: str | None = None
