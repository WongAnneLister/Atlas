"""Typed retrieval metadata shared by the document builder and index."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from support_agent.data.policy_versions import PolicyVersions

SECTION_METADATA_FILE = "section_metadata.json"
DocType = Literal["policy", "catalog"]


class SectionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_type: DocType
    topic: str = Field(min_length=1)
    product_category: str
    effective_from: date
    effective_to: date | None
    region: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_metadata(self) -> SectionMetadata:
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("Section effective_to must be after effective_from")
        if bool(self.product_category) != (self.doc_type == "catalog"):
            raise ValueError("Only catalog sections carry a product category")
        return self


def build_section_metadata(
    policy_topics: Mapping[str, str],
    catalog_categories: Mapping[str, str],
    default_effective_from: date,
    versions: PolicyVersions | None,
) -> dict[str, SectionMetadata]:
    effective_dates: dict[str, tuple[date, date | None]] = {
        sid: (default_effective_from, None) for sid in policy_topics
    }
    topics = dict(policy_topics)
    if versions is not None:
        for entry in versions.entries:
            topics[entry.old_id] = topics[entry.base_section_id]
            effective_dates[entry.base_section_id] = (entry.effective_from, None)
            effective_dates[entry.old_id] = (entry.old.effective_from, entry.old.effective_to)

    metadata = {
        sid: SectionMetadata(
            doc_type="policy",
            topic=topic,
            product_category="",
            effective_from=effective_dates[sid][0],
            effective_to=effective_dates[sid][1],
            region="global",
        )
        for sid, topic in topics.items()
    }
    metadata.update(
        {
            sid: SectionMetadata(
                doc_type="catalog",
                topic="catalog",
                product_category=category,
                effective_from=default_effective_from,
                effective_to=None,
                region="global",
            )
            for sid, category in catalog_categories.items()
        }
    )
    return metadata


def load_section_metadata(folder: Path) -> dict[str, SectionMetadata]:
    path = folder / SECTION_METADATA_FILE
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise ValueError(f"Missing section metadata file {path}; run make data-docs") from exc
    return TypeAdapter(dict[str, SectionMetadata]).validate_json(raw)


def require_section_metadata(metadata: Mapping[str, SectionMetadata], sid: str) -> SectionMetadata:
    if sid not in metadata:
        raise ValueError(f"Missing section metadata for {sid}; run make data-docs")
    return metadata[sid]
