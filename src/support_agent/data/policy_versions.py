"""Synthetic history for selected policy sections."""

from __future__ import annotations

from datetime import date

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from support_agent.config import REPO_ROOT, PolicyVersionSettings, Settings
from support_agent.data.doc_models import digest, json_text


class PolicySection(BaseModel):
    heading: str
    prose: str

    def render(self, section_id: str) -> str:
        return f"## {self.heading}\n<!-- section: {section_id} -->\n\n{self.prose}"


def version_id(base_section_id: str, effective_from: date) -> str:
    return f"{base_section_id}@{effective_from.isoformat()}"


class HistoricalVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    effective_from: date
    effective_to: date
    find: str = Field(min_length=1)
    replace: str = Field(min_length=1)


class VersionedPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_section_id: str = Field(pattern=r"^[a-z0-9_.-]+$")
    effective_from: date
    old: HistoricalVersion

    @model_validator(mode="after")
    def _validate_history(self) -> VersionedPolicy:
        if not self.old.effective_from < self.old.effective_to == self.effective_from:
            raise ValueError("Historical policy must end when the current version starts")
        if self.old.find == self.old.replace:
            raise ValueError("Historical policy must change the source sentence")
        return self

    @property
    def old_id(self) -> str:
        return version_id(self.base_section_id, self.old.effective_from)

    def section_at(self, day: date) -> str:
        if day >= self.effective_from:
            return self.base_section_id
        if self.old.effective_from <= day < self.old.effective_to:
            return self.old_id
        raise ValueError(f"No version of {self.base_section_id} in force on {day}")

    def historical_section(self, base: PolicySection) -> PolicySection:
        if base.prose.count(self.old.find) != 1:
            raise ValueError(f"Expected source sentence exactly once in {self.base_section_id}")
        return PolicySection(
            heading=f"{base.heading} (policy before {self.effective_from})",
            prose=base.prose.replace(self.old.find, self.old.replace, 1),
        )


class PolicyVersions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[VersionedPolicy] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_sections(self) -> PolicyVersions:
        ids = {entry.base_section_id for entry in self.entries}
        if len(ids) != len(self.entries):
            raise ValueError("Duplicate policy version base section")
        return self

    def apply_versions(self, sections: dict[str, PolicySection]) -> dict[str, PolicySection]:
        historical = {}
        for entry in self.entries:
            base = sections.get(entry.base_section_id)
            if base is None:
                raise ValueError(f"Missing policy version base section: {entry.base_section_id}")
            historical[entry.old_id] = entry.historical_section(base)
        return historical


def load_versions(settings: PolicyVersionSettings) -> PolicyVersions:
    path = REPO_ROOT / settings.spec_path
    return PolicyVersions.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def docs_config_hash(settings: Settings, versions: PolicyVersions | None) -> str:
    # Keep the pre-versioning build index identical while versions are disabled.
    config = settings.model_dump(mode="json", exclude={"policy_versions"})
    if versions is not None:
        config["policy_versions"] = settings.policy_versions.model_dump(mode="json")
        config["policy_version_spec"] = versions.model_dump(mode="json")
    return digest(json_text(config))
