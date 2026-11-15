"""Two safety fixes on top of the chunking change: before and after, full graph.

Before: the one-FAQ-per-chunk index without the fixes. After: the same index with the
order-grounding check on the tools path and the explicit-answer rule in the coverage
check. Both settings ran on identical frozen items; answerable sets ran twice.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from eval.chunking_e2e_report import RUNS, section
from eval.e2e_records import E2ERecord
from eval.store_scope_report import load_run
from eval.tools_fallback_report import Comparison, route_ok_ids
from support_agent.config import REPO_ROOT
from support_agent.data.doc_models import write_text

REPORT = Path("eval/reports/safety_fixes.md")


def _runs(*names: str) -> tuple[Path, ...]:
    return tuple(RUNS / f"{name}.jsonl" for name in names)


COMPARISONS = [
    Comparison("Near-miss holdout v1", _runs("chunk-new-v1-r1"), _runs("fix-v1-r1")),
    Comparison("Cross-store holdout v2", _runs("chunk-new-v2-r1"), _runs("fix-v2-r1")),
    Comparison(
        "Paraphrase holdout",
        _runs("chunk-new-para-r1", "chunk-new-para-r2"),
        _runs("fix-para-r1", "fix-para-r2"),
    ),
    Comparison(
        "Dev split",
        # The second before run was cut off at 59/150 (see chunking_e2e.md).
        _runs("chunk-new-dev-r1"),
        _runs("fix-dev-r1", "fix-dev-r2"),
    ),
    Comparison(
        "Answerable store controls",
        _runs("chunk-new-controls-r1", "chunk-new-controls-r2"),
        _runs("fix-controls-r1", "fix-controls-r2"),
    ),
]


def fix_events(record: E2ERecord) -> list[str]:
    """Which fix acted on this request, if any."""
    events = []
    if any(step.startswith("ungrounded:") for step in record.trace):
        events.append("order answer ungrounded")
    if "grounding_error" in record.trace:
        events.append("grounding check error")
    if record.answer_status == "implied_by_absence":
        events.append("answer only implied by absence")
    return events


def fixed_lines(comparison: Comparison) -> list[str]:
    """No-answer items accepted before and handed off after, with the fix that acted."""
    paths = [REPO_ROOT / p for p in [*comparison.before, *comparison.after]]
    if not all(p.exists() for p in paths):
        return []
    before = [load_run(REPO_ROOT / p)[1] for p in comparison.before]
    after = [load_run(REPO_ROOT / p)[1] for p in comparison.after]
    lines = []
    for i in sorted(before[0]):
        record = before[0][i]
        if record.item.answerable or not any(run[i].accepted for run in before):
            continue
        if any(run[i].accepted for run in after):
            continue
        events = sorted({event for run in after for event in fix_events(run[i])})
        cause = ", ".join(events) or f"no fix acted ({after[0][i].handoff_reason})"
        lines.append(f"  - `{i}`: {cause}")
    if not lines:
        return []
    return ["- No-answer items accepted before and handed off after:", *lines, ""]


def grounding_outcomes(comparisons: list[Comparison]) -> list[str]:
    """How the order-grounding check ended, over all after runs."""
    counts: Counter[str] = Counter()
    for comparison in comparisons:
        for path in comparison.after:
            if not (REPO_ROOT / path).exists():
                return []
            for record in load_run(REPO_ROOT / path)[1].values():
                if "grounding_error" in record.trace:
                    counts["check error (fails closed)"] += 1
                elif any(step.startswith("ungrounded:") for step in record.trace):
                    counts["claims without a quote"] += 1
                elif (
                    "tools" in record.trace
                    and "tools_fallback" not in record.trace
                    and record.answer
                    and "handoff" not in record.trace
                ):
                    counts["passed"] += 1
    total = sum(counts.values())
    lines = ["## Order-grounding check outcomes", ""]
    lines.append(f"Tools-path answers that reached the check, all after runs: {total}.")
    lines.append("")
    lines += [f"- {key}: {count}" for key, count in sorted(counts.items())]
    return [*lines, ""]


def event_lines(comparison: Comparison) -> list[str]:
    paths = [REPO_ROOT / p for p in comparison.after]
    if not all(p.exists() for p in paths):
        return []
    counts: Counter[str] = Counter()
    for path in paths:
        for record in load_run(path)[1].values():
            kind = "answerable" if record.item.answerable else "no-answer"
            for event in fix_events(record):
                outcome = "accepted" if record.accepted else "handed off"
                counts[f"{event} ({kind}, finally {outcome})"] += 1
    if not counts:
        return ["- The fixes did not act on any item in the after runs.", ""]
    lines = ["- Fix actions (after runs pooled):"]
    lines += [f"  - {key}: {count}" for key, count in sorted(counts.items())]
    return [*lines, ""]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    route_ok = route_ok_ids()
    lines = [
        "# Safety fixes after the chunking change",
        "",
        "Generated by `make eval-safety-fixes`. The chunking change raised no-answer",
        "false accepts (`eval/reports/chunking_e2e.md`). Two causes were found:",
        "",
        "1. The order-tool path released free text with store rules the tools never",
        "   returned. Now every factual claim must quote this turn's tool data, or the",
        "   question goes to the gated knowledge path (`agent.order_grounding`).",
        "2. The coverage check accepted answers that rest on a source not mentioning",
        "   something. Each part now carries `explicit`; a part that is not explicit",
        "   hands off (`implied_by_absence`).",
        "",
        "Before: one-FAQ-per-chunk index, threshold 0.24, no fixes. After: same plus fixes.",
        "",
    ]
    for comparison in COMPARISONS:
        lines += section(comparison, route_ok)
        lines += fixed_lines(comparison)
        lines += event_lines(comparison)
    lines += grounding_outcomes(COMPARISONS)
    lines += [
        "## Limits",
        "",
        "All runs used the relay endpoint for `deepseek-flash`; it is not deterministic.",
        "Holdouts v1 and v2 ran once per setting; their counts include run-to-run noise.",
        "Holdout v1 was read while finding these causes, so it is no longer unseen.",
        "Closed-list holdout items (a method missing from a full list) now hand off too.",
        "A grounding check error means the model returned no structured call; the",
        "check then fails closed and the question goes to the gated knowledge path.",
        "Holdout items listed with no fix acting changed by run-to-run noise.",
        "All holdouts and controls are agent-authored and unreviewed.",
    ]
    write_text(REPO_ROOT / REPORT, "\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
