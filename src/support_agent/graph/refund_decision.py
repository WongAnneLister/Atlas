"""Refund decision schemas and the code checks every model decision must pass.

A yes or no decision survives only if each reason cites retrieved policy, the items are
real open items of the order with no other request in review, special cases are backed
by cited text, and no retrieved return window is exceeded. Anything else becomes
needs_human (a handoff).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from support_agent.graph.state import ConversationState
from support_agent.orders.models import Order

CITATION = re.compile(r"\[(\d+)\]")
# A return window stated in policy text, e.g. "within 30 days of purchase".
WINDOW = re.compile(r"within (\d+) days of (?:the )?(purchase|delivery)", re.IGNORECASE)
WINDOW_FACT = {"purchase": "days_since_order", "delivery": "days_since_delivery"}


class RefundDecision(BaseModel):
    eligible: Literal["yes", "no", "needs_human"]
    items: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    citations: list[int] = Field(default_factory=list)


class RefundDecisionV2(RefundDecision):
    """Same fields; the descriptions reach the model through the structured-output schema."""

    items: list[str] = Field(
        default_factory=list,
        description="Exact item ids copied from the order facts, nothing else. Empty unless yes.",
    )
    reasons: list[str] = Field(
        default_factory=list,
        description="One sentence each. Every reason ends with the bracketed number of the "
        "policy source it relies on, for example: 'Inside the 30-day return window [1].'",
    )
    citations: list[int] = Field(
        default_factory=list,
        description="The source numbers used in the reasons, ascending, each once.",
    )


DECISION_VERSIONS: dict[str, tuple[str, type[RefundDecision]]] = {
    "v1": ("refund_decide.md", RefundDecision),
    "v2": ("refund_decide_v2.md", RefundDecisionV2),
    "v3": ("refund_decide_v3.md", RefundDecisionV2),
    "v4": ("refund_decide_v4.md", RefundDecisionV2),
}


def check_decision(
    decision: RefundDecision, order: Order, state: ConversationState
) -> RefundDecision:
    valid_citations = sorted(
        {number for number in decision.citations if 1 <= number <= len(state.retrieval)}
    )
    pending = set((state.order_context or {}).get("pending_refund_item_ids") or [])
    valid_items = {
        item.item_id
        for item in order.items
        if item.refunded_quantity < item.quantity and item.item_id not in pending
    }
    cited_numbers = {
        int(number) for reason in decision.reasons for number in CITATION.findall(reason)
    }
    cited_chunks = [
        state.retrieval[number - 1] for number in valid_citations if number in cited_numbers
    ]
    reasons_cited = bool(decision.reasons) and all(
        any(number in valid_citations for number in map(int, CITATION.findall(reason)))
        for reason in decision.reasons
    )
    if decision.eligible == "yes" and (
        not reasons_cited
        or not valid_citations
        or not decision.items
        or not set(decision.items) <= valid_items
    ):
        return decision.model_copy(update={"eligible": "needs_human", "citations": valid_citations})
    if decision.eligible == "no" and (not reasons_cited or not valid_citations):
        return decision.model_copy(update={"eligible": "needs_human", "citations": valid_citations})
    selected_items = set(decision.items)
    if decision.eligible == "yes" and any(
        item.final_sale and item.item_id in selected_items for item in order.items
    ):
        policy_text = " ".join(chunk.text.casefold() for chunk in cited_chunks)
        if "final sale" not in policy_text and "final-sale" not in policy_text:
            return decision.model_copy(
                update={"eligible": "needs_human", "citations": valid_citations}
            )
    # A return-window rule is written for delivered goods. A yes or no for an order in any
    # other status (cancelled, paid, in transit, ...) stands only if a cited source names
    # that status; otherwise the policy does not cover it and a human decides. Without the
    # "no" side, a cancelled order's refund was refused by the 90-day return window.
    if decision.eligible in {"yes", "no"} and order.status.value not in {
        "delivered",
        "partially_refunded",
    }:
        policy_text = " ".join(chunk.text for chunk in cited_chunks)
        if not policy_names_status(policy_text, order.status.value):
            return decision.model_copy(
                update={"eligible": "needs_human", "citations": valid_citations}
            )
    if decision.eligible == "yes" and outside_window(state):
        return decision.model_copy(update={"eligible": "needs_human", "citations": valid_citations})
    if valid_citations != decision.citations:
        return decision.model_copy(update={"eligible": "needs_human", "citations": valid_citations})
    return decision


# Spellings of each order status as policy text writes it.
_STATUS_WORDS = {
    "cancelled": r"(?:cancell?ed)",
    "in_transit": r"(?:in transit)",
    "partially_refunded": r"(?:partially refunded)",
}
_BE = r"(?:that |which )?(?:is |are |was |were |has been |have been )?(?:already )?"


def policy_names_status(policy_text: str, status: str) -> bool:
    """True if the text speaks of orders or items in this status, not just the word.

    "Cancelled orders are refunded" or "if your order has been shipped" name a status;
    "the amount paid" or "pending refunds" do not. A plain substring test let a cited
    "amount paid" stand for a rule about paid orders (27c, ORD-000011).
    """
    word = _STATUS_WORDS.get(status, re.escape(status.replace("_", " ")))
    pattern = rf"\b{word} (?:orders?|items?|purchases?)\b|\b(?:orders?|items?) {_BE}{word}\b"
    return re.search(pattern, policy_text, re.IGNORECASE) is not None


def outside_window(state: ConversationState) -> bool:
    """True if any retrieved policy window is exceeded, or its day count is unknown."""
    context = state.order_context or {}
    for chunk in state.retrieval:
        for days, anchor in WINDOW.findall(chunk.text):
            elapsed = context.get(WINDOW_FACT[anchor.lower()])
            if not isinstance(elapsed, int) or elapsed > int(days):
                return True
    return False
