"""Weighted evidence gate evaluated before knowledge answer generation."""

from __future__ import annotations

from pydantic import BaseModel, Field

from support_agent.config import GateSettings
from support_agent.gate.signals import good_count, key_hit, margin, top_score
from support_agent.retrieval.types import RetrievedChunk


class GateResult(BaseModel):
    score: float = Field(ge=0, le=1)
    signals: dict[str, float]
    passed: bool
    threshold: float = Field(ge=0, le=1)
    reason: str


def evaluate(
    query: str,
    chunks: list[RetrievedChunk],
    settings: GateSettings,
    *,
    allow_untuned: bool = False,
) -> GateResult:
    if settings.threshold is None and not allow_untuned:
        raise ValueError("gate.threshold is unset; pass allow_untuned=True only for tests or demos")
    threshold = settings.threshold if settings.threshold is not None else settings.untuned_threshold
    signals = {
        "top_score": top_score(chunks),
        "good_count": good_count(chunks, settings),
        "margin": margin(chunks),
        "key_hit": key_hit(query, chunks, settings),
    }
    weights = settings.weights.model_dump()
    score = sum(weights[name] * value for name, value in signals.items())
    passed = bool(chunks) and score >= threshold
    reason = "passed" if passed else "empty_retrieval" if not chunks else "below_threshold"
    return GateResult(
        score=score,
        signals=signals,
        passed=passed,
        threshold=threshold,
        reason=reason,
    )
