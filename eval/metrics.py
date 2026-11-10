"""Pure retrieval and answer-safety metrics used by offline experiments."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from math import isfinite


def recall_at_k(ranked_section_ids: Sequence[str], gold: Collection[str], k: int) -> float:
    if k <= 0:
        raise ValueError("k must be positive")
    targets = set(gold)
    return len(set(ranked_section_ids[:k]) & targets) / len(targets) if targets else 0.0


def mrr(ranked_section_ids: Sequence[str], gold: Collection[str]) -> float:
    targets = set(gold)
    return next((1 / rank for rank, sid in enumerate(ranked_section_ids, 1) if sid in targets), 0.0)


def hit_all_at_k(ranked_section_ids: Sequence[str], gold: Collection[str], k: int) -> bool:
    if k <= 0:
        raise ValueError("k must be positive")
    return bool(gold) and set(gold).issubset(ranked_section_ids[:k])


def accepted(trace: Sequence[str], answer: str, handoff: bool) -> bool:
    """A substantive graph answer is accepted; fixed replies and handoffs are not."""
    if handoff or not answer.strip():
        return False
    return any(node in trace for node in ("answer", "tools", "refund_act"))


@dataclass(frozen=True)
class Rates:
    false_accept: float
    false_reject: float
    pass_rate: float
    accepted_count: int
    answerable_count: int
    no_answer_count: int


def outcome_rates(answerable: Sequence[bool], outcomes: Sequence[bool]) -> Rates:
    """Calculate acceptance rates with explicit answerable/no-answer denominators."""
    if len(answerable) != len(outcomes) or not answerable:
        raise ValueError("Labels and outcomes must have the same nonzero length")
    accepted_count = sum(outcomes)
    answerable_count = sum(answerable)
    no_answer_count = len(answerable) - answerable_count
    false_accept = (
        sum(1 for label, outcome in zip(answerable, outcomes, strict=True) if not label and outcome)
        / no_answer_count
        if no_answer_count
        else 0.0
    )
    false_reject = (
        sum(1 for label, outcome in zip(answerable, outcomes, strict=True) if label and not outcome)
        / answerable_count
        if answerable_count
        else 0.0
    )
    return Rates(
        false_accept=false_accept,
        false_reject=false_reject,
        pass_rate=accepted_count / len(answerable),
        accepted_count=accepted_count,
        answerable_count=answerable_count,
        no_answer_count=no_answer_count,
    )


def percentile(values: Sequence[float], percentile_value: float) -> float | None:
    """Return nearest-rank percentile, or None without measurements."""
    if not 0 <= percentile_value <= 100:
        raise ValueError("percentile_value must be between 0 and 100")
    if not values:
        return None
    if any(not isfinite(value) or value < 0 for value in values):
        raise ValueError("latencies must be finite and nonnegative")
    ordered = sorted(values)
    rank = int((percentile_value / 100) * len(ordered) + 0.999999)
    index = max(0, min(len(ordered) - 1, rank - 1))
    return ordered[index]


def sweep_rates(answerable: Sequence[bool], scores: Sequence[float], threshold: float) -> Rates:
    """Apply one evidence threshold to cached scores."""
    if any(not 0 <= score <= 1 for score in scores):
        raise ValueError("gate scores must be in [0, 1]")
    return outcome_rates(answerable, [score >= threshold for score in scores])
