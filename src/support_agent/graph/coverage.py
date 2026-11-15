"""Typed source coverage and deterministic quote/citation validation for knowledge answers."""

from __future__ import annotations

import re

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


def render_covered_answer(
    decision: CoverageAnswer, chunks: list[RetrievedChunk]
) -> tuple[str, str]:
    """Quote membership checks provenance, not semantic entailment or query completeness."""
    if any(not part.supported for part in decision.parts):
        return "insufficient_coverage", ""
    if any(not part.explicit for part in decision.parts):
        return "implied_by_absence", ""
    paragraphs = []
    for part in decision.parts:
        if not part.answer.strip() or not part.evidence or re.search(r"\[\d+\]", part.answer):
            return "invalid_output", ""
        for quote in part.evidence:
            if quote.source > len(chunks):
                return "invalid_evidence", ""
            text = " ".join(chunks[quote.source - 1].text.split())
            if " ".join(quote.quote.split()) not in text:
                return "invalid_evidence", ""
        numbers = sorted({q.source for q in part.evidence})
        paragraphs.append(part.answer.strip() + " " + " ".join(f"[{n}]" for n in numbers))
    return "answered", "\n\n".join(paragraphs)
