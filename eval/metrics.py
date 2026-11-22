"""Pure retrieval and answer-safety metrics used by offline experiments."""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from itertools import product
from math import isfinite
from typing import TYPE_CHECKING

from eval.schema import EvalItem, MultipartItem, MultipartPart
from support_agent.config import get_settings

if TYPE_CHECKING:
    from eval.e2e_records import E2EPart, E2ERecord


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


def _part_words(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.casefold()))


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _align_parts(
    expected: Sequence[MultipartPart], observed: Sequence[E2EPart]
) -> list[E2EPart | None]:
    if len(expected) == len(observed):
        return list(observed)

    minimum = get_settings().eval.multipart_min_overlap
    observed_words = [_part_words(part.text) for part in observed]
    candidates: list[list[tuple[int | None, float]]] = []
    for part in expected:
        words = _part_words(part.text)
        scores = [_jaccard(words, other) for other in observed_words]
        candidates.append(
            [(index, score) for index, score in enumerate(scores) if score >= minimum]
            + [(None, 0.0)]
        )

    # The schema has two gold parts. Try all assignments without reusing an observed part.
    best_score = (-1.0, 0)
    alignment: list[E2EPart | None] = [None] * len(expected)
    for assignment in product(*candidates):
        indices = [index for index, _ in assignment if index is not None]
        if len(indices) != len(set(indices)):
            continue
        score = (sum(overlap for _, overlap in assignment), len(indices))
        if score > best_score:
            best_score = score
            alignment = [observed[index] if index is not None else None for index, _ in assignment]
    return alignment


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
            observed is not None
            and set(expected.gold_sections).issubset(observed.cited_section_ids)
            for expected, observed in zip(
                record.item.parts, _align_parts(record.item.parts, record.parts), strict=True
            )
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
    index = next(index for index, part in enumerate(item.parts) if part.answerable)
    gold = set(item.parts[index].gold_sections)
    if record.parts is None:
        return record.accepted and gold <= _legacy_citations(record)
    part = _align_parts(item.parts, record.parts)[index]
    return (
        part is not None
        and part.answered
        and not part.handed_off
        and gold.issubset(part.cited_section_ids)
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
    index = next(index for index, part in enumerate(item.parts) if not part.answerable)
    part = _align_parts(item.parts, parts)[index]
    return part is not None and part.handed_off and not part.answered


def _wholly_unanswerable(item: EvalItem | MultipartItem) -> bool:
    if isinstance(item, EvalItem):
        return not item.answerable
    return not any(part.answerable for part in item.parts)


def noanswer_false_accept(record: E2ERecord) -> bool:
    """Any rendered part is a false accept on a wholly unanswerable item."""
    if not _wholly_unanswerable(record.item):
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
    if _wholly_unanswerable(record.item):
        metrics["noanswer_false_accept"] = noanswer_false_accept(record)
    return metrics


def claim_support_observations(records: Sequence[E2ERecord]) -> list[bool]:
    """Use individual claims, so long and short answers carry their actual claim counts."""
    return [claim.verdict == "supported" for row in records for claim in row.claims or []]


def claim_answer_metrics(record: E2ERecord) -> dict[str, bool | float]:
    if record.claims is None:
        return {}
    metrics: dict[str, bool | float] = {
        "low_grounding_handoff_rate": record.handoff_reason == "low_grounding",
    }
    if record.claims:
        metrics["answers_with_any_unsupported_claim"] = any(
            claim.verdict != "supported" for claim in record.claims
        )
        metrics["claims_removed_per_answer"] = float(sum(claim.removed for claim in record.claims))
    return metrics
