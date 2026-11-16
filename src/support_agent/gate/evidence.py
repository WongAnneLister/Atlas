"""Weighted evidence gate evaluated before knowledge answer generation."""

from __future__ import annotations

from pydantic import BaseModel, Field

from support_agent.config import GateSettings
from support_agent.gate.signals import (
    good_count,
    key_hit,
    key_terms,
    margin,
    model_number_missed,
    specific_term_missed,
    top_score,
)
from support_agent.retrieval.types import RetrievedChunk

# Gate reasons that are vetoes (a named thing is missing), not low scores.
VETO_REASONS = frozenset({"key_terms_absent", "model_number_absent"})


class GateResult(BaseModel):
    score: float = Field(ge=0, le=1)
    # Signals that took part in the score; key_hit is absent when it was excluded.
    signals: dict[str, float]
    passed: bool
    threshold: float = Field(ge=0, le=1)
    reason: str
    key_terms: list[str] = Field(default_factory=list)


def weighted_score(signals: dict[str, float], settings: GateSettings) -> float:
    """Weighted mean over the signals present, so an excluded signal adds nothing."""
    weights: dict[str, float] = settings.weights.model_dump()
    total = sum(weights[name] for name in signals)
    if total == 0:
        return 0.0
    weighted = sum(weights[name] * value for name, value in signals.items())
    return float(min(1.0, max(0.0, weighted / total)))


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
    }
    hit = key_hit(query, chunks, settings)
    if hit is not None:
        signals["key_hit"] = hit
    score = weighted_score(signals, settings)
    missed = settings.require_specific_term_hit and specific_term_missed(query, chunks, settings)
    model_missed = settings.require_model_number_hit and model_number_missed(
        query, chunks, settings
    )
    passed = bool(chunks) and not missed and not model_missed and score >= threshold
    if passed:
        reason = "passed"
    elif not chunks:
        reason = "empty_retrieval"
    elif missed:
        reason = "key_terms_absent"
    elif model_missed:
        reason = "model_number_absent"
    else:
        reason = "below_threshold"
    return GateResult(
        score=score,
        signals=signals,
        passed=passed,
        threshold=threshold,
        reason=reason,
        key_terms=key_terms(query, settings),
    )
