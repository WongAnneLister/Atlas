"""Weekly handoff improvement-loop job (Commit 31).

Reads handoffs from HandoffQueueStore and produces:
1. eval/reports/doc_gaps.md — kb_gap resolutions grouped by topic/intent
2. eval/sets/candidates_from_handoffs.jsonl — candidate eval items from
   retrieval_miss and gate_too_strict resolutions (unreviewed; ready for review)
3. eval/reports/handoff_loop.md — handoff rates by reason, time-to-claim,
   time-to-resolve, label distribution, and correct_handoff share.

Usage:
  uv run python -m eval.loop_report
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from support_agent.config import REPO_ROOT, get_settings
from support_agent.handoff.models import ALL_RESOLUTION_LABELS, HandoffItem
from support_agent.handoff.store import HandoffQueueStore

logger = logging.getLogger(__name__)
REPORTS_DIR = REPO_ROOT / "eval" / "reports"
SETS_DIR = REPO_ROOT / "eval" / "sets"


@dataclass(frozen=True)
class LoopOutputs:
    total_handoffs: int
    resolved_count: int
    kb_gap_count: int
    candidate_count: int
    correct_handoff_share: float | None
    doc_gaps_md: str
    loop_report_md: str
    candidates: list[dict[str, Any]]


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
    except Exception:
        return "unknown"


def _topic_for(item: HandoffItem) -> str:
    intent = item.payload.get("intent")
    if isinstance(intent, str) and intent.strip():
        return intent.strip()
    return item.reason


def _question_for(item: HandoffItem) -> str:
    rewritten = item.payload.get("rewritten_query")
    if isinstance(rewritten, str) and rewritten.strip():
        return rewritten.strip()
    for msg in item.payload.get("conversation", []):
        if isinstance(msg, dict) and msg.get("type") == "human":
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
    return "(missing question)"


def _human_answer_points(item: HandoffItem) -> list[str]:
    points: list[str] = []
    for entry in item.human_thread:
        if entry.get("sender") == "agent" and isinstance(entry.get("text"), str):
            text = entry["text"].strip()
            if text:
                points.append(text)
    if item.resolution_note and item.resolution_note.strip():
        note = item.resolution_note.strip()
        if note not in points:
            points.append(note)
    return points


def _fmt_duration(values: list[float]) -> str:
    if not values:
        return "n/a"
    med = statistics.median(values)
    mean = statistics.fmean(values)
    return f"median {med:.1f}s / mean {mean:.1f}s (n={len(values)})"


def build_loop_outputs(items: list[HandoffItem]) -> LoopOutputs:
    """Compute doc-gap report, eval candidate records, and loop metrics."""
    resolved = [i for i in items if i.status == "resolved"]
    by_reason = Counter(i.reason for i in items)
    by_label = Counter(i.resolution_label for i in resolved if i.resolution_label)

    claim_secs = [
        max(0.0, (i.claimed_at - i.created_at).total_seconds())
        for i in items
        if i.claimed_at is not None
    ]
    resolve_secs = [
        max(0.0, (i.resolved_at - i.created_at).total_seconds())
        for i in resolved
        if i.resolved_at is not None
    ]

    correct_count = by_label.get("correct_handoff", 0)
    correct_share = (correct_count / len(resolved)) if resolved else None

    # 1. Doc gaps from kb_gap resolutions
    gaps_by_topic: dict[str, list[HandoffItem]] = defaultdict(list)
    for item in resolved:
        if item.resolution_label == "kb_gap":
            gaps_by_topic[_topic_for(item)].append(item)

    gap_lines = [
        "# Documentation Gaps from Human Handoffs",
        "",
        f"- Generated: `{datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}`",
        f"- Git SHA: `{_git_sha()}`",
        f"- Total `kb_gap` resolutions: `{sum(len(v) for v in gaps_by_topic.values())}`",
        "",
    ]
    if not gaps_by_topic:
        gap_lines.append("No `kb_gap` resolutions recorded yet.")
    else:
        for topic in sorted(gaps_by_topic):
            group_items = gaps_by_topic[topic]
            gap_lines.append(f"## Topic: `{topic}` ({len(group_items)})")
            gap_lines.append("")
            for item in group_items:
                q = _question_for(item)
                note = item.resolution_note or "(no note)"
                gap_lines.append(f"- `{item.id}` ({item.reason}): **{q}** — note: {note}")
            gap_lines.append("")

    # 2. Candidate eval items from retrieval_miss & gate_too_strict
    candidates: list[dict[str, Any]] = []
    for idx, item in enumerate(resolved, 1):
        if item.resolution_label not in {"retrieval_miss", "gate_too_strict"}:
            continue
        candidates.append(
            {
                "id": f"ho-cand-{idx:04d}",
                "source_handoff_id": item.id,
                "source_label": item.resolution_label,
                "source_reason": item.reason,
                "group": _topic_for(item),
                "split": "unassigned",
                "question": _question_for(item),
                "gold_sections": [],
                "answer_points": _human_answer_points(item),
                "answerable": True,
                "reviewed": False,
            }
        )

    # 3. Main loop metrics report
    total = len(items)
    loop_lines = [
        "# Handoff Improvement Loop Report (Commit 31)",
        "",
        "## Provenance",
        f"- Generated: `{datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}`",
        f"- Git SHA: `{_git_sha()}`",
        f"- Total handoffs inspected: `{total}` (`{len(resolved)}` resolved)",
        "",
        "## Operational Metrics",
        f"- Time to claim: {_fmt_duration(claim_secs)}",
        f"- Time to resolve: {_fmt_duration(resolve_secs)}",
        (
            f"- Correct handoff share (gate precision proxy): "
            f"`{correct_count}/{len(resolved)}` ({100 * correct_share:.1f}%)"
            if correct_share is not None
            else "- Correct handoff share (gate precision proxy): `n/a` (no resolved handoffs)"
        ),
        f"- Generated `kb_gap` items: `{sum(len(v) for v in gaps_by_topic.values())}`",
        f"- Generated eval candidates (`retrieval_miss` + `gate_too_strict`): `{len(candidates)}`",
        "",
        "## Handoffs by Reason",
        "",
        "| Reason | Count | Share |",
        "|---|---:|---:|",
    ]
    if by_reason:
        for reason, count in by_reason.most_common():
            share = 100.0 * count / total if total else 0.0
            loop_lines.append(f"| `{reason}` | {count} | {share:.1f}% |")
    else:
        loop_lines.append("| *(none)* | 0 | 0.0% |")

    loop_lines.extend(
        [
            "",
            "## Resolution Label Distribution",
            "",
            "| Label | Count | Share of resolved |",
            "|---|---:|---:|",
        ]
    )
    for label in ALL_RESOLUTION_LABELS:
        cnt = by_label.get(label, 0)
        share = (100.0 * cnt / len(resolved)) if resolved else 0.0
        loop_lines.append(f"| `{label}` | {cnt} | {share:.1f}% |")
    loop_lines.append("")

    return LoopOutputs(
        total_handoffs=total,
        resolved_count=len(resolved),
        kb_gap_count=sum(len(v) for v in gaps_by_topic.values()),
        candidate_count=len(candidates),
        correct_handoff_share=correct_share,
        doc_gaps_md="\n".join(gap_lines),
        loop_report_md="\n".join(loop_lines),
        candidates=candidates,
    )


def write_loop_outputs(
    outputs: LoopOutputs,
    *,
    doc_gaps_path: Path = REPORTS_DIR / "doc_gaps.md",
    loop_report_path: Path = REPORTS_DIR / "handoff_loop.md",
    candidates_path: Path = SETS_DIR / "candidates_from_handoffs.jsonl",
) -> None:
    doc_gaps_path.parent.mkdir(parents=True, exist_ok=True)
    loop_report_path.parent.mkdir(parents=True, exist_ok=True)
    candidates_path.parent.mkdir(parents=True, exist_ok=True)

    doc_gaps_path.write_text(outputs.doc_gaps_md, encoding="utf-8")
    loop_report_path.write_text(outputs.loop_report_md, encoding="utf-8")
    with candidates_path.open("w", encoding="utf-8") as fh:
        for rec in outputs.candidates:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate handoff improvement-loop reports.")
    parser.add_argument(
        "--doc-gaps", type=Path, default=REPORTS_DIR / "doc_gaps.md", help="Doc gaps output path"
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=REPORTS_DIR / "handoff_loop.md",
        help="Loop summary report output path",
    )
    parser.add_argument(
        "--candidates",
        type=Path,
        default=SETS_DIR / "candidates_from_handoffs.jsonl",
        help="Candidate eval JSONL output path",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    settings = get_settings()
    store = HandoffQueueStore.from_settings(settings)
    try:
        items = store.list_items(limit=1000)
    finally:
        store.close()

    outputs = build_loop_outputs(items)
    write_loop_outputs(
        outputs,
        doc_gaps_path=args.doc_gaps,
        loop_report_path=args.report,
        candidates_path=args.candidates,
    )
    logger.info(
        "Wrote %s, %s, and %s (%d handoffs, %d resolved, %d candidates)",
        args.report,
        args.doc_gaps,
        args.candidates,
        outputs.total_handoffs,
        outputs.resolved_count,
        outputs.candidate_count,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
