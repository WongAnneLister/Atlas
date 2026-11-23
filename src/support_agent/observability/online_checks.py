"""Cheap per-turn automatic online checks (citation validity, grounding, guardrails)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

_CITATION_MARKER = re.compile(r"\[(\d+)\]")


def check_citation_validity(answer: str, citations: Sequence[Any]) -> bool | None:
    """Verify every [n] marker in the answer maps to a citation record; None if uncited."""
    markers = {int(m) for m in _CITATION_MARKER.findall(answer)}
    valid_nums: set[int] = set()
    for item in citations:
        n = item.get("n") if isinstance(item, dict) else getattr(item, "n", None)
        if isinstance(n, int):
            valid_nums.add(n)
    if not markers and not valid_nums:
        return None
    return bool(markers) and markers.issubset(valid_nums)
