"""Refund decisions on the named fixture orders, per decision version (real decision model).

For each named edge-case order of the first demo customer, run the refund path's policy
retrieval, gate and decision step, and record the model's raw decision and the decision
after the code checks. Retrieval is shared across versions and repeats, so only the version
differs. Expectations come from the generic store policy text. They are agent-authored, except
the orders in REVIEWED, which the author set; they are a sanity check, not gold labels.

The v3 prompt was written after looking at v2 errors on these same named orders. The
window holdout checks it on orders it was not written against: every delivered order of
the other customers without final-sale items or a coupon. Their expectations use the
purchase window from the policy version applicable to the order date.
"""

from __future__ import annotations

import argparse
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from eval.refund_policy_eval import CachingRetriever
from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.data.doc_models import digest, json_text, write_text
from support_agent.data.policy_versions import PolicyVersions, load_versions
from support_agent.graph.deps import GraphDeps
from support_agent.graph.intents import Intent
from support_agent.graph.nodes.refund import RefundPath
from support_agent.graph.refund_decision import CITATION, WINDOW, RefundDecision, outside_window
from support_agent.graph.state import ConversationState
from support_agent.orders.models import Order
from support_agent.orders.service import OrderService

REPORT = Path("eval/reports/refund_decisions.md")
CUSTOMER = "CUST-0001"
VERSIONS = ("v1", "v2", "v3", "v4")
GROUPS = ("named", "window_holdout")
# Generic store policy: returns within 30 days of purchase, final sale not returnable,
# discount-code purchases refund the amount paid, cancellation only before shipping.
# Orders whose expectation the author reviewed on 2026-11-28 (scenarios_v1 v2 uses the same).
REVIEWED = frozenset({"ORD-000002", "ORD-000005", "ORD-000006", "ORD-000007"})
EXPECTED: dict[str, tuple[set[str], str]] = {
    "ORD-000001": ({"yes"}, "11 days since purchase"),
    "ORD-000002": ({"no"}, "35 days since purchase (29 since delivery)"),
    "ORD-000003": ({"no"}, "37 days since purchase"),
    "ORD-000004": ({"no"}, "96 days since purchase"),
    # Set by the author on 2026-11-28: "usually non-returnable ... contact support" leaves doubt.
    "ORD-000005": ({"needs_human"}, "final sale items; policy says usually, ask support"),
    "ORD-000006": ({"yes"}, "coupon order, 11 days; refund the amount paid"),
    # Set by the author on 2026-11-28: the items not yet refunded are an ordinary return.
    "ORD-000007": ({"yes"}, "partly refunded; remaining items in window"),
    "ORD-000008": ({"needs_human"}, "already cancelled"),
    "ORD-000009": ({"no", "needs_human"}, "in transit; cancel only before shipping"),
    "ORD-000010": ({"needs_human"}, "pending; policy never names this status"),
    "ORD-000011": ({"needs_human"}, "paid; policy never names this status"),
    "ORD-000012": ({"no", "needs_human"}, "shipped; cancel only before shipping"),
    "ORD-000013": ({"no", "needs_human"}, "in transit; cancel only before shipping"),
    "ORD-000014": ({"no", "needs_human"}, "everything already refunded"),
}


@dataclass
class Run:
    version: str
    order_id: str
    repeat: int
    gate_passed: bool
    raw: str
    final: str
    causes: list[str] = field(default_factory=list)
    error: str | None = None
    group: str = "named"
    expected: set[str] | None = None
    days_since_order: int | None = None

    @property
    def expected_ok(self) -> bool:
        expected = self.expected if self.expected is not None else EXPECTED[self.order_id][0]
        return self.final in expected


class RecordingRefundPath(RefundPath):
    """Keeps the model's decision before the code checks change it."""

    last_raw: RefundDecision | None = None

    def _check_decision(  # type: ignore[override]
        self, decision: RefundDecision, order: Order, state: ConversationState
    ) -> RefundDecision:
        self.last_raw = decision
        return RefundPath._check_decision(decision, order, state)


def downgrade_causes(raw: RefundDecision, state: ConversationState, order: Order) -> list[str]:
    """Why the code checks would reject a yes/no decision (empty for needs_human)."""
    if raw.eligible == "needs_human":
        return []
    valid = {n for n in raw.citations if 1 <= n <= len(state.retrieval)}
    causes = []
    if not raw.reasons:
        causes.append("no reasons")
    if any(not set(map(int, CITATION.findall(reason))) & valid for reason in raw.reasons):
        causes.append("reason without valid marker")
    if not valid or sorted(valid) != raw.citations:
        causes.append("citations list not sorted unique valid numbers")
    if raw.eligible == "yes":
        open_items = {i.item_id for i in order.items if i.refunded_quantity < i.quantity}
        if not raw.items or not set(raw.items) <= open_items:
            causes.append("items invalid")
        if outside_window(state):
            causes.append("outside a retrieved return window")
    return causes


def holdout_orders(
    service: OrderService, settings: Settings, versions: PolicyVersions
) -> list[tuple[Order, set[str]]]:
    """Delivered orders of other customers, no final sale or coupon, expected by rule."""
    (policy,) = (
        entry for entry in versions.entries if entry.base_section_id.startswith("returns.")
    )
    windows = {}
    for section, sentence in (
        (policy.base_section_id, policy.old.find),
        (policy.old_id, policy.old.replace),
    ):
        matches = [
            int(days) for days, anchor in WINDOW.findall(sentence) if anchor.lower() == "purchase"
        ]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one purchase window for {section}")
        windows[section] = matches[0]
    picked = []
    for customer in service.list_customers(settings.orders.n_customers):
        if customer.customer_id == CUSTOMER:
            continue
        for order in service.list_recent_orders(customer.customer_id, 1000):
            if order.status.value != "delivered" or order.paid_with_coupon:
                continue
            if any(item.final_sale for item in order.items):
                continue
            days = (settings.orders.today - order.order_date).days
            window = windows[policy.section_at(order.order_date)]
            picked.append((order, {"yes"} if days <= window else {"no"}))
    return sorted(picked, key=lambda pair: pair[0].order_id)


def run_one(
    path: RecordingRefundPath,
    order: Order,
    version: str,
    repeat: int,
    group: str = "named",
    expected: set[str] | None = None,
) -> Run:
    state = ConversationState(
        customer_id=order.customer_id,
        intent=Intent.REFUND_REQUEST,
        refund_order_id=order.order_id,
    )
    state = state.model_copy(update=path.load_order(state))
    state = state.model_copy(update=path.retrieve_policy(state))
    gate_passed = bool(state.gate and state.gate.passed)
    days = (state.order_context or {}).get("days_since_order")
    extra = {"group": group, "expected": expected, "days_since_order": days}
    path.last_raw = None
    result = path.decide(state)
    final = (result.get("refund_decision") or {}).get("eligible", "needs_human")
    raw = path.last_raw
    if raw is None:
        error = "gate failed" if not gate_passed else "decision call failed"
        return Run(
            version, order.order_id, repeat, gate_passed, "none", final, error=error, **extra
        )
    causes = downgrade_causes(raw, state, order)
    return Run(version, order.order_id, repeat, gate_passed, raw.eligible, final, causes, **extra)


def _share(part: int, whole: int) -> str:
    return f"{part}/{whole}" if whole else "0/0"


def report_lines(runs: list[Run]) -> list[str]:
    lines = [
        "| Orders | Decision version | Runs | Raw yes/no | Final yes/no | Downgraded by checks "
        "| Final matches expectation | Wrong final yes | Decision call failed |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for group, version in [(g, v) for g in GROUPS for v in VERSIONS]:
        part = [run for run in runs if run.version == version and run.group == group]
        if not part:
            continue
        decided = sum(run.raw in {"yes", "no"} for run in part)
        final = sum(run.final in {"yes", "no"} for run in part)
        lines.append(
            f"| {group} | `{version}` | {len(part)} | {_share(decided, len(part))} "
            f"| {_share(final, len(part))} | {_share(sum(bool(r.causes) for r in part), decided)} "
            f"| {_share(sum(r.expected_ok for r in part), len(part))} "
            f"| {sum(r.final == 'yes' and not r.expected_ok for r in part)} "
            f"| {sum(r.error == 'decision call failed' for r in part)} |"
        )
    lines += ["", "Downgrade causes (a run can have several):", ""]
    lines += ["| Decision version | Cause | Runs |", "|---|---|---:|"]
    for version in VERSIONS:
        counts = Counter(c for run in runs if run.version == version for c in run.causes)
        lines += [f"| `{version}` | {cause} | {n} |" for cause, n in sorted(counts.items())]
    return lines


def holdout_miss_lines(runs: list[Run]) -> list[str]:
    misses = [r for r in runs if r.group == "window_holdout" and not r.expected_ok]
    if not misses:
        return ["No window-holdout run missed its expectation."]
    lines = [
        "| Order | Days since order | Expected | Version | Raw → final |",
        "|---|---:|---|---|---|",
    ]
    for run in sorted(misses, key=lambda r: (r.order_id, r.version, r.repeat)):
        expected = " or ".join(sorted(run.expected or set()))
        lines.append(
            f"| {run.order_id} | {run.days_since_order} | {expected} | `{run.version}` "
            f"| {run.raw} → {run.final} |"
        )
    return lines


def order_lines(runs: list[Run]) -> list[str]:
    head = " | ".join(f"`{p}` raw → final" for p in VERSIONS)
    lines = [
        f"| Order | Expected | Reviewed | Why | {head} |",
        "|---|---|---|---|" + "---|" * len(VERSIONS),
    ]
    for order_id, (expected, why) in EXPECTED.items():
        cells = []
        for version in VERSIONS:
            part = [
                r
                for r in runs
                if r.version == version and r.order_id == order_id and r.group == "named"
            ]
            cells.append(", ".join(f"{r.raw} → {r.final}" for r in part) or "—")
        lines.append(
            f"| {order_id} | {' or '.join(sorted(expected))} | "
            f"{'author' if order_id in REVIEWED else 'no'} | {why} | {' | '.join(cells)} |"
        )
    return lines


def write_report(
    runs: list[Run],
    settings: Settings,
    repeats: int,
    holdout_repeats: int,
    path: Path,
    versions: PolicyVersions,
) -> None:
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    lines = [
        "# Refund decisions on named fixture orders",
        "",
        "Generated by `make eval-refund-decisions`. Do not edit by hand.",
        "",
        f"- Git SHA (base revision): `{sha}`",
        f"- Config hash: `{digest(json_text(settings.model_dump(mode='json')))}`",
        f"- Policy version spec hash: `{digest(json_text(versions.model_dump(mode='json')))}`",
        f"- Date (UTC): {datetime.now(UTC).isoformat()}",
        f"- Decision model: `{settings.llm.main_model}` ({settings.llm.provider}); "
        f"temperature {settings.llm.temperature}.",
        f"- Named: {len(EXPECTED)} edge cases of `{CUSTOMER}`; {repeats} repeats each.",
        f"- Window holdout: {holdout_repeats} run(s) per order per prompt version. Expect `yes`"
        " within the purchase window in force on the stored order date, else `no`.",
        f"- Policy query mode `{settings.refund.policy_query}`; gate threshold "
        f"{settings.gate.threshold}; retrieval shared by all versions.",
        "- Expectations come from the generic store policy text; agent-authored unless the",
        "  Reviewed column says the author set them (2026-11-28).",
        "  v3 was written after reading v2 errors on the named orders, so judge it on the holdout.",
        "- History: a first run of v2 and v3 approved every holdout order 35 days after purchase.",
        "  The return-window code check was added after that run, so the holdout is now seen.",
        "  These are small sanity checks, not a decision-accuracy measurement.",
        "",
        "## Summary",
        "",
        "Raw is the model's decision; final is after the code checks in `refund.py`.",
        "A yes/no decision that fails a check becomes needs_human (a handoff).",
        "Wrong final yes: a final approval where the expectation does not allow yes.",
        "",
        *report_lines(runs),
        "",
        "## Named orders",
        "",
        *order_lines(runs),
        "",
        "## Window holdout misses",
        "",
        *holdout_miss_lines(runs),
        "",
    ]
    write_text(path, "\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--holdout-repeats", type=int, default=1)
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args(argv)
    load_dotenv(REPO_ROOT / ".env", override=False)
    base = get_settings()
    service = OrderService(settings=base.orders)
    orders = [service.get_order(order_id, CUSTOMER) for order_id in EXPECTED]
    policy_versions = load_versions(base.policy_versions)
    holdout = holdout_orders(service, base, policy_versions)
    runs: list[Run] = []
    with GraphDeps(base, order_service=service) as deps:
        retriever = CachingRetriever(deps.knowledge_retriever())
        model = deps.model("main")
        for version in VERSIONS:
            settings = base.model_copy(deep=True)
            settings.refund.decision_version = version
            path = RecordingRefundPath(
                GraphDeps(settings, retriever=retriever, order_service=service, main_model=model)
            )
            for repeat in range(1, args.repeats + 1):
                runs += [run_one(path, order, version, repeat) for order in orders]
            for repeat in range(1, args.holdout_repeats + 1):
                runs += [
                    run_one(path, order, version, repeat, "window_holdout", expected)
                    for order, expected in holdout
                ]
    write_report(
        runs, base, args.repeats, args.holdout_repeats, REPO_ROOT / args.report, policy_versions
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
