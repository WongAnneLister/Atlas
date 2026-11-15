"""Check that an order-tool answer states only facts found in this turn's tool results.

The order model may mix order facts with general claims (store rules, policies) it was
never given. Every factual claim must carry a quote that code finds in the tool data.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_NOT_DATA = re.compile(r"[^\w./-]+", re.UNICODE)


class OrderClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    claim: str = Field(min_length=1)
    quote: str


class OrderGrounding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[OrderClaim]


def _flat(text: str) -> str:
    """Keep words, numbers, dates and ids; JSON quotes, braces and colons do not matter."""
    return " ".join(_NOT_DATA.sub(" ", text).casefold().split())


def tool_data_text(order_context: dict[str, Any] | None) -> str:
    return json.dumps(order_context or {}, sort_keys=True, ensure_ascii=False, default=str)


def ungrounded_claims(decision: OrderGrounding, data_text: str) -> list[str]:
    """Claims whose quote is empty or absent from the tool data."""
    data = f" {_flat(data_text)} "
    return [
        claim.claim
        for claim in decision.claims
        if not _flat(claim.quote) or f" {_flat(claim.quote)} " not in data
    ]
