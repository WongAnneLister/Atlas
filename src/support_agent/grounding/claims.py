"""Typed drafts and verdicts for post-generation knowledge checks."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Verdict = Literal["supported", "partial", "unsupported"]


class GroundingDraft(BaseModel):
    part: int = Field(ge=0)
    question: str = Field(min_length=1)
    text: str = Field(min_length=1)
    source_numbers: list[int] = Field(min_length=1)


class ClaimEvidence(BaseModel):
    n: int = Field(gt=0)
    text: str


class Claim(BaseModel):
    number: int = Field(gt=0)
    part: int = Field(ge=0)
    text: str = Field(min_length=1)
    question: str = Field(min_length=1)
    sources: list[ClaimEvidence]


class ClaimAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part: int = Field(ge=0)
    text: str = Field(min_length=1)
    verdict: Verdict
    reason: str
    removed: bool = False
