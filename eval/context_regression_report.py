"""Render the review regression of commits 26-35 and the answer-layout fix from saved records.

Every number comes from a committed run manifest or metrics file, or from a paired
comparison or gate report written by `make eval-compare` or `eval.gate check`. Per-item rows
stay local, so this report reads only committed files.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.run_record import RUNS, MetricSummary, RunManifest, RunMetrics
from eval.stats import wilson_interval
from support_agent.config import REPO_ROOT, get_settings
from support_agent.data.doc_models import write_text

EVIDENCE = RUNS / "context-regression-28b"
REPORT = REPO_ROOT / "eval/reports/context_regression.md"
E2E_METRICS = ("false_accept", "false_reject", "pass_rate", "full_answer_rate", "citation_validity")
MULTIPART_METRICS = (
    "full_answer_rate",
    "answered_part_correct",
    "unanswerable_part_handed_off",
    "noanswer_false_accept",
)
LABELS = {
    "25b": "25b baseline (`07cf8f5`)",
    "9b73": "after 26-35 (`9b7350e`)",
    "cur": "builder layout (`7f0973a`)",
    "legacy": "all nodes legacy (`7f0973a`)",
    "answer": "answer legacy (`7f0973a`)",
    "fix": "fix: answer legacy",
}
TABLES = {
    "eval_v1 test": ("v1-test", ("25b", "9b73", "fix"), E2E_METRICS),
    "eval_v1 dev": ("v1-dev", ("25b", "9b73", "cur", "legacy", "answer"), E2E_METRICS),
    "Multipart test": ("mp-test", ("25b", "9b73", "fix"), MULTIPART_METRICS),
    "Multipart dev": ("mp-dev", ("25b", "9b73"), MULTIPART_METRICS),
}
COMPARISONS = {
    "eval_v1 test: 25b vs after 26-35": "compare-v1-test-25b-9b73.md",
    "eval_v1 test: after 26-35 vs fix": "compare-v1-test-9b73-fix.md",
    "eval_v1 test: 25b vs fix": "compare-v1-test-25b-fix.md",
    "eval_v1 dev: 25b vs after 26-35": "compare-v1-dev-25b-9b73.md",
    "eval_v1 dev: builder vs all legacy": "compare-v1-dev-cur-legacy.md",
    "eval_v1 dev: builder vs answer legacy": "compare-v1-dev-cur-answer.md",
    "eval_v1 dev: answer legacy vs all legacy": "compare-v1-dev-answer-legacy.md",
    "Multipart test: 25b vs after 26-35": "compare-mp-test-25b-9b73.md",
    "Multipart test: after 26-35 vs fix": "compare-mp-test-9b73-fix.md",
    "Multipart dev: 25b vs after 26-35": "compare-mp-dev-25b-9b73.md",
    "Smoke latency, run alone: 25b vs after 26-35": "compare-latency-25b-9b73.md",
    "Smoke latency, same 25b code: 2026-11-22 vs 2026-11-26": "compare-latency-25b-nov22-today.md",
    "Smoke latency, same day (2026-11-26): 25b vs main `5bb57ac`": (
        "compare-latency-today-25b-main.md"
    ),
}
GATES = {"after 26-35 (`9b7350e`)": "gate-9b73.md", "fix": "gate-fix.md"}


def _runs(evidence: Path) -> dict[str, str]:
    runs: dict[str, str] = json.loads((evidence / "runs.json").read_text(encoding="utf-8"))
    return runs


def _manifest(name: str, root: Path) -> RunManifest:
    return RunManifest.model_validate_json((root / name / "manifest.json").read_bytes())


def _metrics(name: str, root: Path) -> dict[str, MetricSummary]:
    return RunMetrics.model_validate_json((root / name / "metrics.json").read_bytes()).metrics


def _cell(summary: MetricSummary | None) -> str:
    if summary is None:
        return "—"
    if summary.count is None:
        interval = summary.interval
        return f"{interval.point:.4f} [{interval.low:.4f}, {interval.high:.4f}]"
    wilson = wilson_interval(summary.count, summary.n, get_settings().eval.stats.alpha)
    return f"{summary.count}/{summary.n} [{wilson.low:.0%}, {wilson.high:.0%}]"


def _section(text: str, heading: str) -> list[str]:
    lines = text.splitlines()
    start = lines.index(heading) + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("#")), len(lines))
    return [line for line in lines[start:end] if line.startswith("|")]


def provenance_lines(runs: dict[str, str], root: Path) -> list[str]:
    lines = ["## Runs", "", "| Run | Directory | SHA | Dirty | Config |", "|---|---|---|---|---|"]
    for key, name in runs.items():
        manifest = _manifest(name, root)
        lines.append(
            f"| {key} | `{name}` | `{manifest.git_sha[:8]}` | {manifest.dirty} | "
            f"`{manifest.config_hash[:12]}` |"
        )
    return [*lines, ""]


def table_lines(runs: dict[str, str], root: Path) -> list[str]:
    lines: list[str] = []
    for title, (prefix, arms, metrics) in TABLES.items():
        header = "| Run | " + " | ".join(metrics) + " |"
        lines.extend([f"## {title}", "", header, "|" + "---|" * (len(metrics) + 1)])
        for arm in arms:
            values = _metrics(runs[f"{prefix}-{arm}"], root)
            cells = " | ".join(_cell(values.get(metric)) for metric in metrics)
            lines.append(f"| {LABELS[arm]} | {cells} |")
        lines.append("")
    return lines


def comparison_lines(evidence: Path) -> list[str]:
    lines = ["## Paired comparisons (`make eval-compare`, B minus A)", ""]
    for title, file in COMPARISONS.items():
        text = (evidence / file).read_text(encoding="utf-8")
        source = (evidence / file).relative_to(REPO_ROOT)
        rows = _section(text, "## Metric deltas (B minus A)")
        lines.extend([f"### {title}", "", f"Source: `{source}`", "", *rows, ""])
    return lines


def gate_lines(evidence: Path) -> list[str]:
    lines = ["## Release gate (knowledge smoke + red-team smoke)", ""]
    for title, file in GATES.items():
        text = (evidence / file).read_text(encoding="utf-8").splitlines()
        rows = [line for line in text if line.startswith("| ") and "Category" not in line]
        lines.extend([f"### {title}", "", f"- {text[0].lstrip('# ')}", "", *rows, ""])
    return lines


def render(evidence: Path = EVIDENCE, root: Path = RUNS) -> str:
    runs = _runs(evidence)
    lines = [
        "# Context regression after commits 26-35 and the answer-layout fix",
        "",
        "Generated by `make eval-context-regression-report` from committed run records and",
        f"saved outputs in `{evidence.relative_to(REPO_ROOT)}`. Do not edit by hand.",
        "",
        "Real models; index build `4aece1a3` on the local Milvus copy; planning, partial",
        "answers and grounding on; the in-process answer cache off in every run so each item",
        "is answered by the agent. The decision rule for the fix was written before any dev",
        f"ablation result: `{(evidence / 'decisions.md').relative_to(REPO_ROOT)}`. Dev arms",
        "tied, so the fix is the rule's tie-break, not a measured dev gain; test ran once for",
        "the adopted arm. Collection used `--workers 3` and the rerank cache except the gate",
        "smoke and the latency runs, which ran one item at a time. Latency drifts between",
        "days: compare latency only between runs made on the same day, one after the other.",
        "",
        *provenance_lines(runs, root),
        *table_lines(runs, root),
        *comparison_lines(evidence),
        *gate_lines(evidence),
    ]
    return "\n".join(lines).rstrip("\n") + "\n"


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    write_text(REPORT, render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
