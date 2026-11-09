"""Version-one evaluation records and build-only provenance."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

Group = Literal["basic_policy", "model_number", "colloquial", "cross_doc", "no_answer"]
Split = Literal["dev", "test"]
GROUPS: tuple[Group, ...] = ("basic_policy", "model_number", "colloquial", "cross_doc", "no_answer")


class EvalItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1)
    group: Group
    split: Split
    question: str = Field(min_length=1)
    gold_sections: list[str]
    answer_points: list[str]
    answerable: bool = Field(strict=True)
    source: str = Field(min_length=1)
    reviewed: bool = Field(default=False, strict=True)
    notes: str = ""

    @model_validator(mode="after")
    def _consistent_labels(self, info: ValidationInfo) -> EvalItem:
        if self.group == "no_answer":
            if self.answerable or self.gold_sections or self.answer_points:
                raise ValueError("no_answer requires false answerable and empty gold/points")
        elif not self.answerable or not self.gold_sections or not self.answer_points:
            raise ValueError("answerable groups require gold sections and answer points")
        if len(set(self.gold_sections)) != len(self.gold_sections):
            raise ValueError("Duplicate gold sections")
        if any(not value.strip() for value in [*self.gold_sections, *self.answer_points]):
            raise ValueError("Empty gold section or answer point")
        if self.group == "cross_doc" and len(self.gold_sections) < 2:
            raise ValueError(
                "cross_doc needs at least two sections; document identities are validated later"
            )
        if self.group == "cross_doc" and info.context and "section_docs" in info.context:
            documents = {info.context["section_docs"].get(sid) for sid in self.gold_sections}
            if None in documents or len(documents) < 2:
                raise ValueError("cross_doc needs sections from different documents")
        return self


class Candidate(BaseModel):
    item: EvalItem
    family: str
    key_terms: list[str] = Field(default_factory=list)


class Section(BaseModel):
    section_id: str
    doc_id: str
    text: str


class Fact(BaseModel):
    label: str
    value: str
    evidence: str
