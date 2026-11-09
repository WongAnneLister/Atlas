"""Pure section-level metrics; duplicate chunks consume ranking slots."""

from collections.abc import Collection, Sequence


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
