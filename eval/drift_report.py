"""Generate online drift report from OnlineEvalStore (Commit 32).

Usage:
  uv run python -m eval.drift_report
"""

from __future__ import annotations

import argparse
import logging
import subprocess
from datetime import timedelta
from pathlib import Path

from support_agent.config import REPO_ROOT, get_settings
from support_agent.observability.drift import evaluate_drift, render_drift_markdown
from support_agent.observability.online_store import OnlineEvalStore
from support_agent.observability.sampler import sample_for_review

logger = logging.getLogger(__name__)
REPORTS_DIR = REPO_ROOT / "eval" / "reports"


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
    except Exception:
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute online drift report.")
    parser.add_argument(
        "--report",
        type=Path,
        default=REPORTS_DIR / "drift.md",
        help="Output markdown report path",
    )
    parser.add_argument(
        "--reference-days",
        type=int,
        default=4,
        help="Number of initial days treated as the reference window",
    )
    parser.add_argument("--simulated", action="store_true", help="Mark report as simulated replay")
    parser.add_argument("--sample", action="store_true", help="Enqueue stratified review sample")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    settings = get_settings()
    store = OnlineEvalStore.from_settings(settings)
    try:
        events = store.list_turn_events()
        feedback = store.list_feedback()
        if not events:
            ref_ev, cur_ev = [], []
            ref_fb, cur_fb = [], []
        else:
            start = events[0].created_at
            cutoff = start + timedelta(days=args.reference_days)
            ref_ev = [e for e in events if e.created_at < cutoff]
            cur_ev = [e for e in events if e.created_at >= cutoff]
            ref_fb = [f for f in feedback if f.created_at < cutoff]
            cur_fb = [f for f in feedback if f.created_at >= cutoff]

        report = evaluate_drift(
            ref_ev,
            cur_ev,
            ref_fb,
            cur_fb,
            settings.online_eval.drift_thresholds,
        )
        notes: list[str] = []
        if args.sample and cur_ev:
            sampled = sample_for_review(
                cur_ev,
                gate_threshold=settings.gate.threshold,
                sample_size=settings.online_eval.sample_size,
                near_band=settings.online_eval.near_threshold_band,
                near_weight=settings.online_eval.near_threshold_weight,
            )
            for ev in sampled:
                store.enqueue_review(ev)
            notes.append(f"Enqueued {len(sampled)} stratified turns into sampled_reviews.")
        if args.simulated:
            notes.append(
                "Simulated 7-day replay (Days 1-4 reference vs Days 5-7 shifted window); "
                "not real production user traffic."
            )

        md = render_drift_markdown(
            report,
            git_sha=_git_sha(),
            simulated=args.simulated,
            notes=notes,
        )
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(md, encoding="utf-8")
        logger.info(
            "Wrote %s (%d breaches across %d signals)",
            args.report,
            len(report.breaches),
            len(report.signals),
        )
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
