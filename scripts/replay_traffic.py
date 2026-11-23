"""Simulated 7-day traffic replay with a deliberate Day-5 missing-doc surge (Commit 32).

All events generated here are SIMULATED (not real customer traffic) to demonstrate
that drift detection catches the Day-5 distribution shift and surfaces the doc gap.

Usage:
  uv run python scripts/replay_traffic.py
"""

from __future__ import annotations

import argparse
import logging
import random
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.loop_report import build_loop_outputs, write_loop_outputs

from support_agent.config import REPO_ROOT, get_settings
from support_agent.handoff.store import HandoffQueueStore
from support_agent.observability.drift import evaluate_drift, render_drift_markdown
from support_agent.observability.online_store import OnlineEvalStore
from support_agent.observability.sampler import sample_for_review

logger = logging.getLogger(__name__)
REPORTS_DIR = REPO_ROOT / "eval" / "reports"

_NORMAL_INTENTS = [
    ("policy_question", "knowledge", 0.30),
    ("product_question", "knowledge", 0.25),
    ("order_status", "tools", 0.20),
    ("shipping_delivery", "tools", 0.10),
    ("refund_request", "after_sales", 0.10),
    ("chitchat_other", "fixed", 0.05),
]
_NORMAL_QUESTIONS = [
    "What is the return window for electronics?",
    "How do I clean the filter on my Philips BHD340/10?",
    "Where is my order ORD-000012?",
    "How long does standard shipping take?",
    "Can I return an unopened hair dryer?",
]
_SHIFT_TOPIC_QUESTIONS = [
    "Can I transfer my Philips warranty to a second-hand buyer?",
    "Do gift cards work for international warranty replacements?",
    "Can I pay for international shipping with crypto or gift cards?",
    "Does warranty transfer apply if I bought the dryer as a gift abroad?",
    "How do I register a transferred warranty for an international order?",
]


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
    except Exception:
        return "unknown"


def run_simulated_week(
    *,
    seed: int = 32,
    turns_per_day: int = 40,
    drift_report_path: Path = REPORTS_DIR / "drift.md",
    doc_gaps_path: Path | None = None,
) -> tuple[int, int]:
    """Run a deterministic 7-day simulated replay (Days 1-4 normal, Days 5-7 shifted)."""
    settings = get_settings()
    rng = random.Random(seed)
    online_store = OnlineEvalStore.from_sqlite_path(":memory:")
    handoff_store = HandoffQueueStore.from_sqlite_path(":memory:")

    base_start = datetime(2026, 11, 16, 8, 0, tzinfo=UTC)
    intents = [x[0] for x in _NORMAL_INTENTS]
    paths = {x[0]: x[1] for x in _NORMAL_INTENTS}
    weights = [x[2] for x in _NORMAL_INTENTS]

    try:
        for day in range(7):
            is_shift = day >= 4  # Day 5..7 (0-indexed 4..6)
            for idx in range(turns_per_day):
                ts = base_start + timedelta(days=day, minutes=idx * 15)
                conv_id = f"sim-d{day + 1}-c{idx:03d}"
                cust_id = f"SIM-CUST-{(idx % 20) + 1:02d}"

                if is_shift and rng.random() < 0.55:
                    # Deliberate Day-5 surge on a topic missing from the policy docs
                    intent = "policy_question"
                    path = "knowledge"
                    question = rng.choice(_SHIFT_TOPIC_QUESTIONS)
                    gate_score = round(rng.uniform(0.01, 0.14), 4)
                    gate_passed = False
                    handoff_reason: str | None = "low_evidence"
                    tokens = rng.randint(4200, 5600)
                    cost = round(tokens * 0.0000018, 6)
                    rewrite_skipped = rng.random() < 0.25
                    rating = "down" if rng.random() < 0.45 else "up"
                else:
                    intent = rng.choices(intents, weights=weights, k=1)[0]
                    path = paths[intent]
                    question = rng.choice(_NORMAL_QUESTIONS)
                    if path == "knowledge":
                        gate_score = round(rng.uniform(0.45, 0.92), 4)
                        gate_passed = True
                        handoff_reason = "low_evidence" if rng.random() < 0.08 else None
                        if handoff_reason:
                            gate_score = round(rng.uniform(0.02, 0.14), 4)
                            gate_passed = False
                    else:
                        gate_score = None
                        gate_passed = None
                        handoff_reason = "complaint" if rng.random() < 0.04 else None
                    tokens = rng.randint(1800, 3200)
                    cost = round(tokens * 0.0000012, 6)
                    rewrite_skipped = rng.random() < 0.70
                    rating = "down" if rng.random() < 0.07 else "up"

                online_store.record_turn_event(
                    conversation_id=conv_id,
                    customer_id=cust_id,
                    trace_id=f"tr-{conv_id}",
                    intent=intent,
                    path=path,
                    gate_score=gate_score,
                    gate_passed=gate_passed,
                    handoff_reason=handoff_reason,
                    rewrite_skipped=rewrite_skipped,
                    tokens_total=tokens,
                    cost_usd=cost,
                    citation_valid=True if (path == "knowledge" and not handoff_reason) else None,
                    claims_removed=0,
                    guardrail_flags=[],
                    question_text=question,
                    answer_text=(
                        "Transferred to a human agent."
                        if handoff_reason
                        else "Answered with policy citation [1]."
                    ),
                    now=ts,
                )
                if rng.random() < 0.40:
                    online_store.record_feedback(
                        message_id=f"msg-{conv_id}",
                        conversation_id=conv_id,
                        customer_id=cust_id,
                        rating=rating,  # type: ignore[arg-type]
                        reason="Missing policy info" if rating == "down" else None,
                        trace_id=f"tr-{conv_id}",
                        now=ts + timedelta(seconds=30),
                    )
                if handoff_reason == "low_evidence" and is_shift:
                    item = handoff_store.enqueue(
                        conversation_id=conv_id,
                        customer_id=cust_id,
                        reason=handoff_reason,
                        priority="normal",
                        payload={"rewritten_query": question, "intent": intent},
                        idempotency_key=f"sim-ho-{conv_id}",
                        now=ts,
                    )
                    # Simulated demo resolution for the doc-gap demonstration only
                    handoff_store.claim(item.id, "sim-reviewer", now=ts + timedelta(seconds=60))
                    handoff_store.resolve(
                        item.id,
                        agent_id="sim-reviewer",
                        label="kb_gap",
                        note=(
                            "Simulated Day-5 missing topic: "
                            "international warranty transfer / gift cards."
                        ),
                        now=ts + timedelta(seconds=180),
                    )

        cutoff = base_start + timedelta(days=4)
        all_events = online_store.list_turn_events()
        all_fb = online_store.list_feedback()
        ref_ev = [e for e in all_events if e.created_at < cutoff]
        cur_ev = [e for e in all_events if e.created_at >= cutoff]
        ref_fb = [f for f in all_fb if f.created_at < cutoff]
        cur_fb = [f for f in all_fb if f.created_at >= cutoff]

        report = evaluate_drift(
            ref_ev,
            cur_ev,
            ref_fb,
            cur_fb,
            settings.online_eval.drift_thresholds,
        )
        sampled = sample_for_review(
            cur_ev,
            gate_threshold=settings.gate.threshold,
            sample_size=settings.online_eval.sample_size,
            near_band=settings.online_eval.near_threshold_band,
            near_weight=settings.online_eval.near_threshold_weight,
            seed=seed,
        )
        loop_out = build_loop_outputs(handoff_store.list_items(limit=500))

        notes = [
            (
                "SIMULATED DATA: generated by `scripts/replay_traffic.py` "
                "(seed=32, 40 turns/day x 7 days)."
            ),
            (
                "Days 1-4 represent steady baseline traffic; Days 5-7 inject a surge of questions "
                "on a missing KB topic (international warranty transfer / gift cards)."
            ),
            f"Stratified nightly sampler selected {len(sampled)} answered turns for human review.",
            (
                f"Simulated Day-5 missing-topic handoffs surfaced {loop_out.kb_gap_count} "
                "`kb_gap` items under topic `policy_question`."
            ),
        ]
        md = render_drift_markdown(report, git_sha=_git_sha(), simulated=True, notes=notes)
        drift_report_path.parent.mkdir(parents=True, exist_ok=True)
        drift_report_path.write_text(md, encoding="utf-8")

        if doc_gaps_path is not None:
            write_loop_outputs(
                loop_out,
                doc_gaps_path=doc_gaps_path,
                loop_report_path=doc_gaps_path.with_name("handoff_loop_simulated.md"),
                candidates_path=doc_gaps_path.with_name("candidates_simulated.jsonl"),
            )
        return len(report.breaches), loop_out.kb_gap_count
    finally:
        online_store.close()
        handoff_store.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run simulated 7-day drift replay.")
    parser.add_argument("--seed", type=int, default=32)
    parser.add_argument("--turns-per-day", type=int, default=40)
    parser.add_argument("--report", type=Path, default=REPORTS_DIR / "drift.md")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    breaches, kb_gaps = run_simulated_week(
        seed=args.seed,
        turns_per_day=args.turns_per_day,
        drift_report_path=args.report,
    )
    logger.info(
        "Simulated week complete: %d drift breaches, %d simulated kb_gap handoffs -> %s",
        breaches,
        kb_gaps,
        args.report,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
