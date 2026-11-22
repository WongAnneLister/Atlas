"""Typed source coverage and deterministic quote/citation validation for knowledge answers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from support_agent.retrieval.types import RetrievedChunk


class SourceQuote(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source: int = Field(gt=0, strict=True)
    quote: str = Field(min_length=1)


class CoveredPart(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1)
    supported: bool = Field(strict=True)
    # True only when a quote states the answer itself. An answer that rests on the
    # sources not mentioning something (an absent feature, a method missing from a
    # list) is not explicit and is never released.
    explicit: bool = Field(strict=True)
    answer: str
    evidence: list[SourceQuote]


class CoverageAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parts: list[CoveredPart] = Field(min_length=1)


CoverageStatus = Literal[
    "answered", "insufficient_coverage", "implied_by_absence", "invalid_output", "invalid_evidence"
]


def render_covered_part(
    part: CoveredPart, sources: Mapping[int, RetrievedChunk]
) -> tuple[CoverageStatus, str, list[int]]:
    """Verify quotations against the sources assigned to this part."""
    if not part.supported:
        return "insufficient_coverage", "", []
    if not part.explicit:
        return "implied_by_absence", "", []
    if not part.answer.strip() or not part.evidence or re.search(r"\[\d+\]", part.answer):
        return "invalid_output", "", []
    for quote in part.evidence:
        chunk = sources.get(quote.source)
        if chunk is None or " ".join(quote.quote.split()) not in " ".join(chunk.text.split()):
            return "invalid_evidence", "", []
    numbers = sorted({quote.source for quote in part.evidence})
    return "answered", part.answer.strip() + " " + " ".join(f"[{n}]" for n in numbers), numbers


def render_covered_answer(
    decision: CoverageAnswer, chunks: list[RetrievedChunk]
) -> tuple[CoverageStatus, str]:
    """Quote membership checks provenance, not semantic entailment or query completeness."""
    if any(not part.supported for part in decision.parts):
        return "insufficient_coverage", ""
    if any(not part.explicit for part in decision.parts):
        return "implied_by_absence", ""
    sources = dict(enumerate(chunks, 1))
    paragraphs = []
    for part in decision.parts:
        status, paragraph, _ = render_covered_part(part, sources)
        if status != "answered":
            return status, ""
        paragraphs.append(paragraph)
    return "answered", "\n\n".join(paragraphs)
