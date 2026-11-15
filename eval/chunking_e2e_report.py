"""Chunking change through the full graph: false rejects, false accepts and prompt size.

Before runs use the token-window index with its own threshold (0.15, no text dedupe);
after runs use the one-FAQ-per-chunk index with the dev-selected threshold (0.24) and
text dedupe. Answerable sets ran twice per setting, so consistent gains and losses can
be told apart from run-to-run noise of the relay model.
"""

from __future__ import annotations

import argparse
import statistics
from pathlib import Path

from eval.e2e_records import E2ERecord
from eval.store_scope_report import family, load_run
from eval.tools_fallback_report import Comparison, rates, route_ok_ids
from support_agent.config import REPO_ROOT
from support_agent.data.doc_models import write_text

REPORT = Path("eval/reports/chunking_e2e.md")
RUNS = Path("eval/runs")


def _runs(*names: str) -> tuple[Path, ...]:
    return tuple(RUNS / f"{name}.jsonl" for name in names)


COMPARISONS = [
    Comparison(
        "Paraphrase holdout (fresh)",
        _runs("chunk-old-para-r1", "chunk-old-para-r2"),
        _runs("chunk-new-para-r1", "chunk-new-para-r2"),
    ),
    Comparison(
        "Answerable store controls",
        _runs("fb-controls-r1", "fb-controls-r2"),
        _runs("chunk-new-controls-r1", "chunk-new-controls-r2"),
    ),
    Comparison(
        "Dev split",
        _runs("fb-dev-r1", "fb-dev-r2"),
        # The second after run was cut off (59/150) when the session ended.
        _runs("chunk-new-dev-r1"),
    ),
    Comparison("Cross-store holdout v2", _runs("fb-v2-r1"), _runs("chunk-new-v2-r1")),
    Comparison("Near-miss holdout v1", _runs("chunk-old-v1-r1"), _runs("chunk-new-v1-r1")),
]


def median_tokens(run: dict[str, E2ERecord], ids: list[str]) -> str:
    """Median input tokens of all model calls in a request, over requests that answered."""
    values = [run[i].input_tokens for i in ids if run[i].input_tokens and "answer" in run[i].trace]
    return f"{statistics.median(values):.0f} ({len(values)})" if values else "n/a"


def consistent(
    before: list[dict[str, E2ERecord]], after: list[dict[str, E2ERecord]], ids: list[str]
) -> tuple[list[str], list[str]]:
    gained = [
        i
        for i in ids
        if all(not run[i].accepted for run in before) and all(run[i].accepted for run in after)
    ]
    lost = [
        i
        for i in ids
        if all(run[i].accepted for run in before) and all(not run[i].accepted for run in after)
    ]
    return gained, lost


def family_rows(
    before: list[dict[str, E2ERecord]], after: list[dict[str, E2ERecord]], ids: list[str]
) -> list[str]:
    families: dict[str, list[str]] = {}
    for i in ids:
        families.setdefault(family(before[0][i]), []).append(i)
    if len(families) < 2:
        return []
    lines = ["| Family | Items | Accepted before (per run) | Accepted after (per run) |"]
    lines.append("|---|---:|---:|---:|")
    for name, members in sorted(families.items()):
        cells = [
            ", ".join(str(sum(run[i].accepted for i in members)) for run in runs)
            for runs in (before, after)
        ]
        lines.append(f"| {name} | {len(members)} | {cells[0]} | {cells[1]} |")
    return [*lines, ""]


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
    members = [i for i in ids if i not in route_ok]
    lines = [f"## {comparison.label}", ""]
    if len(members) != len(ids):
        lines += [
            f"Items whose order or human route is also correct are left out: "
            f"{len(ids) - len(members)}.",
            "",
        ]
    lines += [
        "| Setting | Run | False reject | False accept | Median input tokens (answered) |",
        "|---|---:|---:|---:|---:|",
    ]
    for label, runs in (("before", before), ("after", after)):
        for number, run in enumerate(runs, 1):
            fr, fa = rates(run, members)
            lines.append(f"| {label} | {number} | {fr} | {fa} | {median_tokens(run, members)} |")
    lines.append("")
    answerable = [i for i in members if before[0][i].item.answerable]
    if answerable:
        gained, lost = consistent(before, after, answerable)
        lines += [
            f"- Rejected in every before run, accepted in every after run: {len(gained)}",
            f"- Accepted in every before run, rejected in every after run: {len(lost)}",
        ]
        lines += [f"  - lost `{i}`: {after[0][i].handoff_reason}" for i in lost]
        for name, runs in (("before", before), ("after", after)):
            if len(runs) > 1:
                noise = sum(runs[0][i].accepted != runs[1][i].accepted for i in members)
                lines.append(f"- Noise floor ({name}): {noise} outcomes flip between two runs.")
        lines.append("")
        lines += family_rows(before, after, answerable)
    wrong = sorted(
        {i for run in after for i in members if not run[i].item.answerable and run[i].accepted}
    )
    if any(not before[0][i].item.answerable for i in members):
        lines += [f"- No-answer items accepted in an after run: {len(wrong)}"]
        lines += [f"  - `{i}`" for i in wrong]
        lines.append("")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    route_ok = route_ok_ids()
    lines = [
        "# Chunking change, full graph",
        "",
        "Generated by `make eval-chunking-e2e`. Before: token-window index, threshold",
        "0.15, no text dedupe. After: one FAQ per chunk, headed manual windows, text",
        "dedupe, threshold 0.24 (dev-selected in `eval/reports/chunking.md`). Everything",
        "else (store filter, gate weights, coverage check, fallback) is the same.",
        "",
        "Decision: the after setting raised no-answer false accepts on both holdouts, so",
        "the default config keeps the token-window index. The after setting is opt-in:",
        "`SUPPORT_AGENT__MILVUS__COLLECTION=support_chunks_faq_v1`,",
        "`SUPPORT_AGENT__CHUNK__STRATEGY=faq_unit`, `SUPPORT_AGENT__GATE__THRESHOLD=0.24`,",
        "`SUPPORT_AGENT__RETRIEVAL__DEDUPE_TEXT=true`.",
        "",
        "Rates show count/total with Wilson 95% intervals. Input tokens are all model",
        "input tokens of one request, over requests that reached the answer step.",
        "",
    ]
    for comparison in COMPARISONS:
        lines += section(comparison, route_ok)
    lines += [
        "## Limits",
        "",
        "All runs used the relay endpoint for `deepseek-flash`; it is not deterministic.",
        "Holdouts v1 and v2 ran once per setting; their counts include run-to-run noise.",
        "All holdouts and controls are agent-authored and unreviewed.",
        "Before runs for dev, controls and v2 are the tools-fallback after runs (13j).",
        "Rows that failed on a relay or tunnel error were re-run; format errors were kept.",
        "Dev after has one run only: the second was cut off at 59 of 150 items.",
    ]
    write_text(REPO_ROOT / REPORT, "\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
