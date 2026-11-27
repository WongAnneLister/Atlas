"""Fit the answer prompt's sources into the answer token budget.

The answer node puts its sources inside one input message, so the ContextBuilder cannot
trim them, and the legacy layout never checked the budget at all. A few catalog chunks hold
a whole product manual (thousands of tokens), so one retrieval could push the answer
prompt far past its budget, and the claim check then overflowed on its own budget.

The rule matches the builder's evidence rule: drop the lowest-ranked source first, and
keep at least one source per question part. If the prompt still does not fit, the caller
hands off with `context_overflow`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from support_agent.retrieval.types import RetrievedChunk

T = TypeVar("T")
Sources = dict[int, dict[int, RetrievedChunk]]


def fit_sources(
    candidates: Sources, attempt: Callable[[Sources], T | None]
) -> tuple[Sources, T, int] | None:
    """Drop lowest-ranked sources until `attempt` succeeds.

    `candidates` maps each part to its sources in rank order. Returns the kept sources,
    the attempt's result and the number dropped, or None when one source per part still
    does not fit.
    """
    kept: Sources = {part: dict(sources) for part, sources in candidates.items()}
    dropped = 0
    while True:
        result = attempt(kept)
        if result is not None:
            return kept, result, dropped
        # The lowest-ranked source left: the deepest position among parts that keep two or
        # more; on a tie, the later part.
        droppable = [(len(sources), part) for part, sources in kept.items() if len(sources) > 1]
        if not droppable:
            return None
        _, part = max(droppable)
        last = list(kept[part])[-1]
        del kept[part][last]
        dropped += 1
