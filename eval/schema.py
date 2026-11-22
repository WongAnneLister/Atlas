"""Evaluation records and build-only provenance."""

from __future__ import annotations

from datetime import date
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

Group = Literal[
    "basic_policy", "model_number", "colloquial", "cross_doc", "no_answer", "time_sensitive"
]
MultipartGroup = Literal["answerable_pair", "half_answerable", "both_unanswerable"]
TimeSensitivePath = Literal["knowledge", "refund"]
Split = Literal["dev", "test"]
# Frozen v1 strata for v1 generation, validation and smoke sampling.
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


class TimeSensitiveItem(EvalItem):
    group: Literal["time_sensitive"] = "time_sensitive"
    path: TimeSensitivePath
    as_of: date
    version_of: str = Field(min_length=1)
    order_id: str | None = Field(default=None, min_length=1)
    customer_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _validate_policy_case(self) -> TimeSensitiveItem:
        if self.path == "refund":
            if self.order_id is None or self.customer_id is None:
                raise ValueError("Refund path requires order_id and customer_id")
        elif self.order_id is not None or self.customer_id is not None:
            raise ValueError("Knowledge path does not accept order or customer ids")
        if len(self.gold_sections) != 1:
            raise ValueError("Time-sensitive cases require a single gold version")
        return self


class MultipartPart(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1)
    gold_sections: list[str]
    answer_points: list[str]
    answerable: bool = Field(strict=True)
    source_item_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent_labels(self) -> MultipartPart:
        if self.answerable:
            if len(self.gold_sections) != 1 or not self.answer_points:
                raise ValueError("Answerable parts require one gold section and answer points")
            if any(not value.strip() for value in [*self.gold_sections, *self.answer_points]):
                raise ValueError("Empty gold section or answer point")
        elif self.gold_sections or self.answer_points:
            raise ValueError("Unanswerable parts require empty gold sections and answer points")
        return self


class MultipartItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1)
    split: Split
    group: MultipartGroup
    question: str = Field(min_length=1)
    source: str = Field(min_length=1)
    parts: list[MultipartPart] = Field(min_length=2, max_length=2)
    reviewed: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def _consistent_parts(self) -> MultipartItem:
        left, right = self.parts
        if left.source_item_id == right.source_item_id:
            raise ValueError("Multipart items require distinct source item ids")
        expected = {
            "answerable_pair": 2,
            "half_answerable": 1,
            "both_unanswerable": 0,
        }[self.group]
        if sum(part.answerable for part in self.parts) != expected:
            raise ValueError(f"Part answerability does not match {self.group}")
        return self


ClaimVerdict = Literal["supported", "partial", "unsupported"]
ClaimLabel = Literal["supported", "unsupported"]
ClaimPerturbation = Literal["number", "duration", "amount", "model", "uncited_sentence"]


CLAIM_PERTURBATIONS: tuple[ClaimPerturbation, ...] = get_args(ClaimPerturbation)


class ClaimSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n: int = Field(gt=0)
    section_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class ClaimItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    split: Split
    group: Literal["real", "synthetic"]
    source_run: str = Field(min_length=1)
    source_item: str = Field(min_length=1)
    part: int = Field(ge=0)
    sentence: int = Field(ge=0)
    question: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    sources: list[ClaimSource]
    label: ClaimLabel | None = None
    label_source: Literal["human", "construction"]
    perturbation: ClaimPerturbation | None = None
    reviewed: bool = False
    note: str = ""

    @model_validator(mode="after")
    def _consistent_provenance(self) -> ClaimItem:
        if len({source.n for source in self.sources}) != len(self.sources):
            raise ValueError("Claim source numbers must be unique")
        if self.group == "synthetic":
            if (
                self.label_source != "construction"
                or self.perturbation is None
                or self.label is not None
                or self.reviewed
                or self.note
            ):
                raise ValueError("Synthetic claims require a perturbation and blank human labels")
        elif (
            self.label_source != "human"
            or self.perturbation is not None
            or self.reviewed != (self.label is not None)
        ):
            raise ValueError("Real claims require consistent human label provenance")
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
