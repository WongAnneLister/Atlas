"""Offline checks for the refund decision prompt switch and the decision report."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from eval.refund_decision_eval import (
    EXPECTED,
    VERSIONS,
    Run,
    downgrade_causes,
    holdout_orders,
    report_lines,
)

from support_agent.config import Settings
from support_agent.data.policy_versions import load_versions
from support_agent.graph.deps import GraphDeps
from support_agent.graph.handoff import PROMPTS as PROMPT_DIR
from support_agent.graph.nodes.refund import RefundPath
from support_agent.graph.refund_decision import RefundDecision, RefundDecisionV2, check_decision
from support_agent.graph.state import ConversationState
from support_agent.orders.models import Order, OrderItem, OrderStatus
from support_agent.retrieval.types import RetrievedChunk


def order() -> Order:
    item = OrderItem(
        item_id="ITEM-1",
        product_id="P-1",
        model="BHD340/10",
        name="Philips BHD340/10",
        category="Hair Dryers",
        quantity=1,
        unit_price=Decimal("10.00"),
        final_sale=False,
        refunded_quantity=0,
    )
    return Order(
        order_id="ORD-000001",
        customer_id="CUST-0001",
        status=OrderStatus.DELIVERED,
        order_date=date(2026, 11, 1),
        delivered_at=date(2026, 11, 4),
        currency="USD",
        total=Decimal("10.00"),
        paid_with_coupon=False,
        coupon_code=None,
        items=[item],
    )


@pytest.mark.parametrize(
    ("version", "prompt", "schema"),
    [
        ("v1", "refund_decide.md", RefundDecision),
        ("v2", "refund_decide_v2.md", RefundDecisionV2),
        ("v3", "refund_decide_v3.md", RefundDecisionV2),
        ("v4", "refund_decide_v4.md", RefundDecisionV2),
    ],
)
def test_decision_version_selects_prompt_and_schema(
    version: str, prompt: str, schema: type[RefundDecision]
) -> None:
    settings = Settings()
    settings.refund.decision_version = version  # type: ignore[assignment]
    path = RefundPath(GraphDeps(settings))
    assert path.prompt == (PROMPT_DIR / prompt).read_text(encoding="utf-8")
    assert path.decision_schema is schema


def test_v2_schema_asks_for_markers_and_parses_as_a_decision() -> None:
    schema = RefundDecisionV2.model_json_schema()["properties"]
    assert "[1]" in schema["reasons"]["description"]
    raw = {"eligible": "no", "reasons": ["Late [1]."], "citations": [1]}
    parsed = RefundPath._parse_decision(raw)
    assert isinstance(parsed, RefundDecision)


def test_unknown_decision_version_is_rejected() -> None:
    with pytest.raises(ValueError):
        Settings(refund={"decision_version": "v9"})


def test_causes_match_the_code_checks() -> None:
    good = RefundDecision(
        eligible="yes", items=["ITEM-1"], reasons=["Inside 30 days [1]."], citations=[1]
    )
    assert downgrade_causes(good, _window_state(11), order()) == []
    bad = RefundDecision(
        eligible="yes",
        items=["ITEM-9"],
        reasons=["Inside 30 days [1].", "Delivered 5 days ago."],
        citations=[1, 1],
    )
    assert downgrade_causes(bad, _window_state(35), order()) == [
        "reason without valid marker",
        "citations list not sorted unique valid numbers",
        "items invalid",
        "outside a retrieved return window",
    ]
    assert (
        downgrade_causes(RefundDecision(eligible="needs_human"), _window_state(35), order()) == []
    )


def test_summary_counts_raw_final_and_expectation() -> None:
    runs = [
        Run(VERSIONS[0], "ORD-000001", 1, True, "yes", "needs_human", ["reason without marker"]),
        Run(VERSIONS[1], "ORD-000001", 1, True, "yes", "yes"),
    ]
    lines = report_lines(runs)
    assert lines[2] == f"| named | `{VERSIONS[0]}` | 1 | 1/1 | 0/1 | 1/1 | 0/1 | 0 | 0 |"
    assert lines[3] == f"| named | `{VERSIONS[1]}` | 1 | 1/1 | 1/1 | 0/1 | 1/1 | 0 | 0 |"
    assert set(EXPECTED["ORD-000001"][0]) == {"yes"}


def test_holdout_runs_use_their_own_expectation() -> None:
    late = Run(
        VERSIONS[2],
        "ORD-000200",
        1,
        True,
        "yes",
        "yes",
        group="window_holdout",
        expected={"no"},
        days_since_order=40,
    )
    assert not late.expected_ok
    lines = report_lines([late])
    assert lines[2].startswith(f"| window_holdout | `{VERSIONS[2]}` | 1 |")
    assert lines[2].endswith("| 0/1 | 1 | 0 |")


def test_holdout_uses_the_configured_purchase_window_on_each_order_date() -> None:
    from types import SimpleNamespace

    settings = Settings()
    settings.orders.today = date(2026, 10, 3)
    versions = load_versions(settings.policy_versions)
    returns = next(
        entry for entry in versions.entries if entry.base_section_id.startswith("returns.")
    )
    returns.old.replace = "Returns are allowed within 33 days of purchase."
    prior = order().model_copy(update={"order_date": date(2026, 8, 31), "order_id": "old"})
    current = order().model_copy(update={"order_date": date(2026, 9, 1), "order_id": "current"})

    class Orders:
        def list_customers(self, limit: int) -> list[SimpleNamespace]:
            return [SimpleNamespace(customer_id="CUST-0002")]

        def list_recent_orders(self, customer_id: str, limit: int) -> list[Order]:
            return [prior, current]

    assert holdout_orders(Orders(), settings, versions) == [(current, {"no"}), (prior, {"yes"})]


def _window_state(days_since_order: int | None) -> ConversationState:
    chunk = RetrievedChunk(
        chunk_id="c1",
        doc_id="returns",
        section_id="returns.maktek_faqs.generic-store",
        title="Returns",
        heading_path="Returns > Generic store",
        text="Return products within 30 days of purchase for a full refund.",
        n_tokens=10,
        scores={"rerank": 0.9},
    )
    context = {"days_since_delivery": 5}
    if days_since_order is not None:
        context["days_since_order"] = days_since_order
    return ConversationState(retrieval=[chunk], order_context=context)


@pytest.mark.parametrize(
    ("days", "final"), [(11, "yes"), (30, "yes"), (35, "needs_human"), (None, "needs_human")]
)
def test_yes_outside_a_retrieved_purchase_window_goes_to_a_human(
    days: int | None, final: str
) -> None:
    decision = RefundDecision(
        eligible="yes", items=["ITEM-1"], reasons=["Inside the window [1]."], citations=[1]
    )
    assert check_decision(decision, order(), _window_state(days)).eligible == final


def test_window_check_leaves_no_decisions_alone() -> None:
    decision = RefundDecision(eligible="no", reasons=["Window expired [1]."], citations=[1])
    assert check_decision(decision, order(), _window_state(35)).eligible == "no"


def test_the_shipped_config_uses_the_adopted_v3_decision_prompt() -> None:
    # Adopted in 12e under the rule in eval/runs/refund-v3-12d/decisions.md.
    from support_agent.config import get_settings

    assert get_settings().refund.decision_version == "v3"


def test_v4_says_a_policy_covers_orders_placed_inside_its_validity_dates() -> None:
    # 12f: under v3 the model sent an in-window order bought under the old 90-day policy to a
    # human, because that policy is "valid until 2026-09-01" and today is later (sim-017).
    v3 = (PROMPT_DIR / "refund_decide_v3.md").read_text(encoding="utf-8")
    v4 = (PROMPT_DIR / "refund_decide_v4.md").read_text(encoding="utf-8")
    rule = "a source applies to an order whose order_date falls inside them, even when today"
    assert rule not in v3 and rule in v4
    assert set(v3.splitlines()) <= set(v4.splitlines())
