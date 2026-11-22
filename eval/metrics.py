"""Pure retrieval and answer-safety metrics used by offline experiments."""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING

from eval.schema import MultipartItem

if TYPE_CHECKING:
    from eval.e2e_records import E2ERecord


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


def _gold_sections(record: E2ERecord) -> set[str]:
    if isinstance(record.item, MultipartItem):
        return {section for part in record.item.parts for section in part.gold_sections}
    return set(record.item.gold_sections)


def _legacy_citations(record: E2ERecord) -> set[str]:
    return {source["section_id"] for source in record.cited_sources if "section_id" in source}


def _part_key(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"\w+", text.casefold()))


def full_answer(record: E2ERecord) -> bool:
    """Measure full cited coverage using validated output and frozen gold sections."""
    gold = _gold_sections(record)
    if not gold or not record.accepted or record.handoff_reason is not None:
        return False
    if record.parts is None:
        return gold <= _legacy_citations(record)
    if any(
        not part.answered or part.handed_off or not part.cited_section_ids for part in record.parts
    ):
        return False
    if isinstance(record.item, MultipartItem):
        return all(
            any(
                _part_key(observed.text) == _part_key(expected.text)
                and set(expected.gold_sections).issubset(observed.cited_section_ids)
                for observed in record.parts
            )
            for expected in record.item.parts
        )
    return gold <= {section for part in record.parts for section in part.cited_section_ids}


def part_recall_at_5(record: E2ERecord) -> bool:
    """Count a question only when every gold section appears in some part's top five."""
    gold = _gold_sections(record)
    if record.parts is None:
        return hit_all_at_k(record.retrieved_section_ids, gold, 5)
    seen = {section for part in record.parts for section in part.retrieved_section_ids[:5]}
    return bool(gold) and gold <= seen


def partial_answer(record: E2ERecord) -> bool:
    """A mixed outcome has both a rendered answer and a handoff."""
    return (
        not record.accepted
        and record.handoff_reason is not None
        and any(part.answered for part in record.parts or [])
    )


def answered_part_correct(record: E2ERecord) -> bool:
    """Check that a half-answer's answerable part was rendered with its gold citations."""
    item = record.item
    if not isinstance(item, MultipartItem) or item.group != "half_answerable":
        return False
    expected = next(part for part in item.parts if part.answerable)
    gold = set(expected.gold_sections)
    if record.parts is None:
        return record.accepted and gold <= _legacy_citations(record)
    key = _part_key(expected.text)
    return any(
        part.answered
        and not part.handed_off
        and _part_key(part.text) == key
        and gold.issubset(part.cited_section_ids)
        for part in record.parts
    )


def unanswerable_part_handed_off(record: E2ERecord) -> bool:
    """Accept a whole handoff or an explicit handoff of the expected unsupported part."""
    item = record.item
    if (
        not isinstance(item, MultipartItem)
        or item.group != "half_answerable"
        or record.handoff_reason is None
        or record.accepted
    ):
        return False
    parts = record.parts or []
    if not any(part.answered for part in parts):
        return True
    expected = next(part for part in item.parts if not part.answerable)
    matches = [part for part in parts if _part_key(part.text) == _part_key(expected.text)]
    return any(part.handed_off for part in matches) and not any(part.answered for part in matches)


def noanswer_false_accept(record: E2ERecord) -> bool:
    """Any rendered part is a false accept on a wholly unanswerable item."""
    if record.item.group not in {"no_answer", "both_unanswerable"}:
        return False
    return record.accepted or any(part.answered for part in record.parts or [])


def part_metric_values(record: E2ERecord) -> dict[str, bool | float]:
    """Return only the metrics for which this row is in the denominator."""
    metrics: dict[str, bool | float] = {}
    group = record.item.group
    if group in {"cross_doc", "answerable_pair"}:
        metrics["full_answer_rate"] = full_answer(record)
    if group == "cross_doc" or isinstance(record.item, MultipartItem):
        metrics["partial_answer_rate"] = partial_answer(record)
    if _gold_sections(record):
        metrics["part_recall_at_5"] = part_recall_at_5(record)
    if group == "half_answerable":
        metrics["answered_part_correct"] = answered_part_correct(record)
        metrics["unanswerable_part_handed_off"] = unanswerable_part_handed_off(record)
    if group in {"no_answer", "both_unanswerable"}:
        metrics["noanswer_false_accept"] = noanswer_false_accept(record)
    return metrics
