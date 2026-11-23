"""Stratified turn sampling for nightly human review and candidate export."""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from support_agent.observability.online_store import SampledReviewRecord, TurnEventRecord


def _bucket(score: float | None, threshold: float, band: float) -> str:
    if score is None:
        return "no_gate"
    if abs(score - threshold) <= band:
        return "near_threshold"
    return "high" if score > threshold else "low"


def sample_for_review(
    events: Sequence[TurnEventRecord],
    *,
    gate_threshold: float,
    sample_size: int = 20,
    near_band: float = 0.10,
    near_weight: float = 0.50,
    seed: int = 42,
) -> list[TurnEventRecord]:
    """Sample answered turns stratified by intent and gate bucket, oversampling near-threshold."""
    answered = [ev for ev in events if ev.handoff_reason is None]
    if not answered or sample_size <= 0:
        return []
    if len(answered) <= sample_size:
        return list(answered)

    rng = random.Random(seed)
    near = [
        ev
        for ev in answered
        if _bucket(ev.gate_score, gate_threshold, near_band) == "near_threshold"
    ]
    other = [
        ev
        for ev in answered
        if _bucket(ev.gate_score, gate_threshold, near_band) != "near_threshold"
    ]

    near_target = min(len(near), max(1 if near else 0, round(sample_size * near_weight)))
    other_target = min(len(other), sample_size - near_target)
    if near_target + other_target < sample_size:
        near_target = min(len(near), sample_size - other_target)

    def _stratified_pick(pool: list[TurnEventRecord], k: int) -> list[TurnEventRecord]:
        if k <= 0 or not pool:
            return []
        by_intent: dict[str, list[TurnEventRecord]] = defaultdict(list)
        for ev in pool:
            by_intent[ev.intent or "unknown"].append(ev)
        intents = sorted(by_intent)
        for intent in intents:
            rng.shuffle(by_intent[intent])
        picked: list[TurnEventRecord] = []
        while len(picked) < k:
            progressed = False
            for intent in intents:
                if by_intent[intent] and len(picked) < k:
                    picked.append(by_intent[intent].pop())
                    progressed = True
            if not progressed:
                break
        return picked

    chosen = _stratified_pick(near, near_target) + _stratified_pick(other, other_target)
    return chosen[:sample_size]


def export_review_candidates(reviews: Sequence[SampledReviewRecord]) -> list[dict[str, Any]]:
    """Convert reviewed turns with issues into unreviewed eval candidates."""
    candidates: list[dict[str, Any]] = []
    for idx, rev in enumerate(reviews, 1):
        if rev.status != "reviewed" or rev.rubric_label in {None, "correct"}:
            continue
        candidates.append(
            {
                "id": f"rev-cand-{idx:04d}",
                "source_review_id": rev.id,
                "source_label": rev.rubric_label,
                "group": rev.intent or "unknown",
                "split": "unassigned",
                "question": rev.question_text,
                "gold_sections": [],
                "answer_points": [rev.note] if rev.note else [],
                "answerable": rev.rubric_label != "should_have_handed_off",
                "reviewed": False,
            }
        )
    return candidates
