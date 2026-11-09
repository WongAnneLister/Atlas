"""Pure reciprocal rank fusion; input ranks start at one."""

import math


def rrf(rank_lists: dict[str, list[str]], k: int) -> list[tuple[str, float]]:
    if k < 0:
        raise ValueError("RRF k must be nonnegative")
    contributions: dict[str, list[float]] = {}
    best: dict[str, int] = {}
    for ids in rank_lists.values():
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate chunk ids in one ranking")
        for rank, chunk_id in enumerate(ids, start=1):
            contributions.setdefault(chunk_id, []).append(1 / (k + rank))
            best[chunk_id] = min(best.get(chunk_id, rank), rank)
    scores = [(chunk_id, math.fsum(values)) for chunk_id, values in contributions.items()]
    return sorted(scores, key=lambda pair: (-pair[1], best[pair[0]], pair[0]))
