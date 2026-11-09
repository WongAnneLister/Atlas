"""Assign related questions together before fixed-seed stratified sampling."""

from __future__ import annotations

import random
from collections import Counter
from itertools import combinations

from eval.common import near_duplicate, normalised
from eval.schema import GROUPS, Candidate, EvalItem
from support_agent.config import EvalSettings


def sample_split(
    candidates: list[Candidate], config: EvalSettings
) -> tuple[list[EvalItem], dict[str, int]]:
    unique: dict[str, Candidate] = {}
    for item in candidates:
        unique.setdefault(normalised(item.item.question), item)
    pool = list(unique.values())
    parent = list(range(len(pool)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def merge(left: int, right: int) -> None:
        parent[root(right)] = root(left)

    families: dict[str, int] = {}
    for index, item in enumerate(pool):
        if item.family in families:
            merge(index, families[item.family])
        families[item.family] = index
    for left, right in combinations(range(len(pool)), 2):
        if root(left) != root(right) and near_duplicate(
            pool[left].item.question, pool[right].item.question, config
        ):
            merge(left, right)
    components = sorted({root(index) for index in range(len(pool))})
    rng = random.Random(config.seed)
    quotas = {"dev": config.dev_per_group, "test": config.per_group - config.dev_per_group}
    assigned: dict[int, str] = {}
    for _ in range(config.split_search_attempts):
        assigned = {component: rng.choice(["dev", "test"]) for component in components}
        counts = Counter(
            (item.item.group, assigned[root(index)]) for index, item in enumerate(pool)
        )
        if all(
            counts[group, split] >= quota for group in GROUPS for split, quota in quotas.items()
        ):
            break
    else:
        sizes = Counter(root(index) for index in range(len(pool)))
        raise ValueError(
            f"Cannot fill split quotas without leakage; components={len(sizes)}, "
            f"largest={max(sizes.values(), default=0)}, available={dict(counts)}"
        )
    sampled: list[EvalItem] = []
    for group in GROUPS:
        for split, quota in quotas.items():
            eligible = [
                item.item
                for index, item in enumerate(pool)
                if item.item.group == group and assigned[root(index)] == split
            ]
            for item in rng.sample(eligible, quota):
                sampled.append(EvalItem.model_validate({**item.model_dump(), "split": split}))
    return sorted(sampled, key=lambda item: item.id), {
        "duplicate_candidates_removed": len(candidates) - len(pool),
        "split_components": len(components),
    }
