"""Tools-to-knowledge fallback: false rejects and false accepts before and after.

Before runs used the same code and settings except the fallback (store filter on).
Answerable sets ran twice per setting, so consistent gains and losses can be told
apart from run-to-run noise. Holdouts check that the fallback adds no wrong answers.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from eval.common import load_items
from eval.e2e_records import E2ERecord
from eval.gate_round3 import rate_cell
from eval.store_scope_report import load_run
from support_agent.config import REPO_ROOT
from support_agent.data.doc_models import write_text

REPORT = Path("eval/reports/tools_fallback.md")
CONTROLS = Path("eval/sets/store_controls_v1.jsonl")


@dataclass(frozen=True)
class Comparison:
    label: str
    before: tuple[Path, ...]
    after: tuple[Path, ...]


COMPARISONS = [
    Comparison(
        "Answerable store controls",
        (Path("eval/runs/fr-controls-on-r1.jsonl"), Path("eval/runs/fr-controls-on-r2.jsonl")),
        (Path("eval/runs/fb-controls-r1.jsonl"), Path("eval/runs/fb-controls-r2.jsonl")),
    ),
    Comparison(
        "Dev split",
        (Path("eval/runs/fr-dev-on-r1.jsonl"), Path("eval/runs/fr-dev-on-r2.jsonl")),
        (Path("eval/runs/fb-dev-r1.jsonl"), Path("eval/runs/fb-dev-r2.jsonl")),
    ),
    Comparison(
        "Cross-store holdout v2",
        (Path("eval/runs/store-v2-after.jsonl"),),
        (Path("eval/runs/fb-v2-r1.jsonl"),),
    ),
    Comparison(
        "Near-miss holdout v1",
        (Path("eval/runs/store-v1-after.jsonl"),),
        (Path("eval/runs/fb-v1-r1.jsonl"),),
    ),
]


def fell_back(record: E2ERecord) -> bool:
    return "tools_fallback" in record.trace


def route_ok_ids() -> set[str]:
    path = REPO_ROOT / CONTROLS
    if not path.exists():
        return set()
    return {i.id for i in load_items(path) if json.loads(i.notes).get("route_ok")}


def rates(run: dict[str, E2ERecord], ids: list[str]) -> tuple[str, str]:
    answerable = [i for i in ids if run[i].item.answerable]
    no_answer = [i for i in ids if not run[i].item.answerable]
    fr = (
        rate_cell(sum(not run[i].accepted for i in answerable), len(answerable))
        if answerable
        else "n/a"
    )
    fa = rate_cell(sum(run[i].accepted for i in no_answer), len(no_answer)) if no_answer else "n/a"
    return fr, fa


def section(comparison: Comparison, route_ok: set[str]) -> list[str]:
    paths = [*comparison.before, *comparison.after]
    missing = [p for p in paths if not (REPO_ROOT / p).exists()]
    if missing:
        return [f"## {comparison.label}", "", f"Not measured: missing `{missing[0]}`.", ""]
    before = [load_run(REPO_ROOT / p)[1] for p in comparison.before]
    after = [load_run(REPO_ROOT / p)[1] for p in comparison.after]
    ids = sorted(before[0])
    if any(sorted(run) != ids for run in [*before, *after]):
        raise ValueError(f"{comparison.label}: runs cover different items")
    subsets = {"all items": ids}
    if any(i in route_ok for i in ids):
        subsets["policy-only items"] = [i for i in ids if i not in route_ok]
        subsets["order/human route also correct"] = [i for i in ids if i in route_ok]
    lines = [f"## {comparison.label}", ""]
    for subset, members in subsets.items():
        lines += [
            f"**{subset}** ({len(members)})",
            "",
            "| Setting | Run | False reject | False accept |",
            "|---|---:|---:|---:|",
        ]
        for label, runs in (("before", before), ("after", after)):
            for number, run in enumerate(runs, 1):
                fr, fa = rates(run, members)
                lines.append(f"| {label} | {number} | {fr} | {fa} |")
        lines.append("")
    taken = [(n, i) for n, run in enumerate(after, 1) for i in ids if fell_back(run[i])]
    outcomes: dict[str, int] = {}
    for n, i in taken:
        record = after[n - 1][i]
        key = "accepted" if record.accepted else f"handoff {record.handoff_reason}"
        key = f"{'answerable' if record.item.answerable else 'no-answer'}: {key}"
        outcomes[key] = outcomes.get(key, 0) + 1
    lines += [f"- Fallback taken (all after runs pooled): {len(taken)}"]
    lines += [f"  - {key}: {count}" for key, count in sorted(outcomes.items())]
    answerable = [i for i in ids if before[0][i].item.answerable]
    gained = [
        i
        for i in answerable
        if all(not run[i].accepted for run in before) and all(run[i].accepted for run in after)
    ]
    lost = [
        i
        for i in answerable
        if all(run[i].accepted for run in before) and all(not run[i].accepted for run in after)
    ]
    via_fallback = sum(any(fell_back(run[i]) for run in after) for i in gained)
    lost_via_fallback = sum(any(fell_back(run[i]) for run in after) for i in lost)
    if answerable:
        lines += [
            f"- Answerable items rejected in every before run and accepted in every after run: "
            f"{len(gained)} (via fallback: {via_fallback})",
            f"- Answerable items accepted in every before run and rejected in every after run: "
            f"{len(lost)} (via fallback: {lost_via_fallback})",
            "- Fallback rescues (accepted after, rejected in the paired before run): "
            + ", ".join(
                str(
                    sum(
                        fell_back(run[i]) and run[i].accepted and not prior[i].accepted
                        for i in answerable
                    )
                )
                for prior, run in zip(before, after, strict=False)
            ),
        ]
        if len(before) > 1:
            noise = sum(before[0][i].accepted != before[1][i].accepted for i in ids)
            lines.append(f"- Noise floor: {noise} outcomes flip between the two before runs.")
    wrong = [
        (n, i)
        for n, run in enumerate(after, 1)
        for i in ids
        if not run[i].item.answerable and run[i].accepted and fell_back(run[i])
    ]
    lines.append(f"- No-answer items accepted through the fallback: {len(wrong)}")
    lines += [f"  - `{i}` (after run {n})" for n, i in wrong]
    return [*lines, ""]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    route_ok = route_ok_ids()
    lines = [
        "# Tools-to-knowledge fallback",
        "",
        "Generated by `make eval-tools-fallback`. When the order model calls no tool,",
        "the question goes to retrieval, the evidence gate and the coverage check",
        "instead of a handoff. A failed lookup, a tool outage or a human request still",
        "hands off. Before runs are the same code without the fallback.",
        "",
    ]
    for comparison in COMPARISONS:
        lines += section(comparison, route_ok)
    lines += [
        "## Limits",
        "",
        "All runs used the relay endpoint for `deepseek-flash`; it is not deterministic.",
        "Holdouts ran once per setting; their counts include run-to-run noise.",
        "Store controls are agent-authored and unreviewed; route_ok is a label fix (13i).",
        "Dev was used to choose the gate threshold, not this change.",
    ]
    write_text(REPO_ROOT / REPORT, "\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
