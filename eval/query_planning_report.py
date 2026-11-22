"""Render the commit 24b query planning evidence from committed run records and saved outputs.

Every number comes from a run manifest or metrics file, a paired comparison or gate report
written by its own command, or `summary.json`, which `--save-summary` computes from the local
per-item rows. Per-item rows stay local, so the report itself reads only committed files.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

from eval.run_record import RUNS, MetricSummary, RunManifest, RunMetrics
from eval.stats import wilson_interval
from support_agent.config import REPO_ROOT, get_settings
from support_agent.data.doc_models import write_text

EVIDENCE = RUNS / "query-planning-24b"
REPORT = REPO_ROOT / "eval/reports/query_planning.md"
CONFIGS = ("off", "plan", "pp")
LABELS = {
    "off": "planning off",
    "plan": "planning, partial answers off",
    "pp": "planning + partial answers",
}
MULTIPART_METRICS = (
    "full_answer_rate",
    "answered_part_correct",
    "unanswerable_part_handed_off",
    "partial_answer_rate",
    "noanswer_false_accept",
    "part_recall_at_5",
)
E2E_METRICS = (
    "false_accept",
    "false_reject",
    "pass_rate",
    "full_answer_rate",
    "part_recall_at_5",
    "graph_recall_at_5",
    "citation_validity",
)
COMPARISONS = {
    "eval_v1 test, planning off vs planning + partial": "compare-v1-test.md",
    "eval_v1 dev, planning off vs planning + partial": "compare-v1-dev.md",
    "multipart test, planning off vs planning": "compare-mp-test-off-plan.md",
    "multipart test, planning vs planning + partial": "compare-mp-test-plan-pp.md",
    "multipart test, planning off vs planning + partial": "compare-mp-test-off-pp.md",
    "Latency, smoke set run alone, planning off vs planning + partial": "compare-latency.md",
}


def _runs(evidence: Path) -> dict[str, str]:
    runs: dict[str, str] = json.loads((evidence / "runs.json").read_text(encoding="utf-8"))
    return runs


def _manifest(name: str, root: Path) -> RunManifest:
    return RunManifest.model_validate_json((root / name / "manifest.json").read_bytes())


def _metrics(name: str, root: Path) -> dict[str, MetricSummary]:
    return RunMetrics.model_validate_json((root / name / "metrics.json").read_bytes()).metrics


def _cell(summary: MetricSummary | None) -> str:
    """Counts get a 95% Wilson interval; other metrics keep the run's bootstrap interval."""
    if summary is None:
        return "—"
    interval = summary.interval
    if summary.count is None:
        return f"{interval.point:.4f} [{interval.low:.4f}, {interval.high:.4f}]"
    wilson = wilson_interval(summary.count, summary.n, get_settings().eval.stats.alpha)
    return f"{summary.count}/{summary.n} [{wilson.low:.0%}, {wilson.high:.0%}]"


def _section(text: str, heading: str) -> list[str]:
    lines = text.splitlines()
    start = lines.index(heading) + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("#")), len(lines))
    return [line for line in lines[start:end] if line.startswith("|")]


def _rule(header: str) -> str:
    return "|" + "---|" * (header.count("|") - 1)


def provenance_lines(runs: dict[str, str], root: Path) -> list[str]:
    lines = ["## Runs", "", "| Run | Directory | SHA | Dirty | Config |", "|---|---|---|---|---|"]
    for key, name in runs.items():
        manifest = _manifest(name, root)
        lines.append(
            f"| {key} | `{name}` | `{manifest.git_sha[:8]}` | {manifest.dirty} | "
            f"`{manifest.config_hash[:12]}` |"
        )
    return [*lines, ""]


def e2e_lines(runs: dict[str, str], root: Path) -> list[str]:
    lines = ["## eval_v1 (full graph)", ""]
    for split in ("test", "dev"):
        header = "| Config | " + " | ".join(E2E_METRICS) + " |"
        lines.extend([f"### {split}", "", header, _rule(header)])
        for config in ("off", "pp"):
            values = _metrics(runs[f"v1-{split}-{config}"], root)
            lines.append(
                f"| {LABELS[config]} | "
                + " | ".join(_cell(values.get(metric)) for metric in E2E_METRICS)
                + " |"
            )
        lines.append("")
    return lines


def multipart_lines(evidence: Path) -> list[str]:
    lines = ["## Multipart set (frozen `multipart_v1`)", ""]
    for split in ("test", "dev"):
        lines.extend([f"### {split}", ""])
        for config in CONFIGS:
            text = (evidence / f"mp-{split}-{config}.md").read_text(encoding="utf-8")
            rows = [
                line
                for line in text.splitlines()
                if line.startswith(f"| {split} |")
                and any(f"| {metric} |" in line for metric in MULTIPART_METRICS)
            ]
            lines.extend(
                [
                    f"{LABELS[config]} (from `mp-{split}-{config}.md`):",
                    "",
                    "| Split | Group | Metric | Estimate and interval |",
                    "|---|---|---|---|",
                    *rows,
                    "",
                ]
            )
    return lines


def comparison_lines(evidence: Path) -> list[str]:
    lines = ["## Paired comparisons (`make eval-compare`)", ""]
    for title, file in COMPARISONS.items():
        text = (evidence / file).read_text(encoding="utf-8")
        lines.extend(
            [
                f"### {title}",
                "",
                f"Source: `{(evidence / file).relative_to(REPO_ROOT)}`",
                "",
                *_section(text, "## Metric deltas (B minus A)"),
                "",
            ]
        )
    return lines


def gate_lines(evidence: Path) -> list[str]:
    lines = ["## Release gate (knowledge smoke + red-team smoke)", ""]
    for title, file in (
        ("Before the metric fix `788ab30`", "gate-before.md"),
        ("After the metric fix, same saved run rescored", "gate-after.md"),
    ):
        text = (evidence / file).read_text(encoding="utf-8").splitlines()
        lines.extend([f"### {title}", "", f"- {text[0].lstrip('# ')}"])
        lines.extend(line for line in text if line.startswith(("| graph_recall", "| false_accept")))
        lines.append("")
    redteam = (evidence / "gate-after.md").read_text(encoding="utf-8")
    lines.extend(["### Red-team smoke", "", *_section(redteam, "## Red-team smoke"), ""])
    return lines


def summary_lines(evidence: Path) -> list[str]:
    data: dict[str, Any] = json.loads((evidence / "summary.json").read_text(encoding="utf-8"))
    lines = ["## Planner reach, model calls and discarded runs", ""]
    lines.append("| Run | Planner called | Split into parts | Not split (whole route) |")
    lines.append("|---|---:|---:|---:|")
    for key, row in data["reach"].items():
        lines.append(
            f"| {key} | {row['planner']}/{row['n']} | {row['parts']}/{row['n']} | "
            f"{row['whole']}/{row['n']} |"
        )
    lines.extend(["", "| Run | Model calls per question | Input tokens | Output tokens |"])
    lines.append("|---|---:|---:|---:|")
    for key, row in data["usage"].items():
        lines.append(
            f"| {key} | {row['calls']:.2f} | {row['input_tokens']:.0f} | "
            f"{row['output_tokens']:.0f} |"
        )
    lines.extend(["", "Multipart questions the pre-check did not send to the planner:", ""])
    for key, row in data["precheck_miss"].items():
        lines.append(
            f"- {key}: {row['missed']}/{row['n']}; joined as `and also For <store>:` in "
            f"{row['for_store']} of them."
        )
    lines.extend(
        ["", "Discarded runs (remote Milvus tunnel drop at 20:57; rerun on local Milvus):", ""]
    )
    for key, row in data["discarded"].items():
        lines.append(
            f"- {key}: {row['dependency_unavailable']}/{row['n']} handed off as "
            "`dependency_unavailable`."
        )
    judge = data.get("judge")
    if judge:
        lines.extend(
            [
                "",
                f"Judge on partial answers (multipart test, planning + partial): "
                f"{judge['flagged']}/{judge['judged']} flagged. Findings in "
                f"{judge['unnecessary_handoff_mentions']} rows call a handoff unnecessary (keyword "
                "count): the judge reads the generic store warranty FAQ as an answer to product "
                "warranty questions that eval_v1 labels unanswerable. Human review is pending; the "
                "review CSV stays local.",
            ]
        )
    return [*lines, ""]


def render(evidence: Path = EVIDENCE, root: Path = RUNS) -> str:
    runs = _runs(evidence)
    lines = [
        "# Query planning — commit 24b evidence",
        "",
        "Generated by `make eval-query-planning-report` from committed run records and saved",
        f"outputs in `{evidence.relative_to(REPO_ROOT)}`. Do not edit by hand.",
        "",
        "All runs: real models, index build `4aece1a3` served from a local Milvus 2.5.10 copy",
        "whose 210 chunks and vectors are bit-identical to the remote build. Dev was used for",
        "review only; nothing was tuned. eval_v1 runs and the smoke run were rescored with the",
        "per-part graph recall fix (`788ab30`); their manifests keep the collection SHA.",
        "Latency rows from parallel lanes are not comparable; use the smoke latency comparison.",
        "",
        *provenance_lines(runs, root),
        *e2e_lines(runs, root),
        *multipart_lines(evidence),
        *comparison_lines(evidence),
        *gate_lines(evidence),
        *summary_lines(evidence),
    ]
    return "\n".join(lines).rstrip("\n") + "\n"


def _items(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (path / "items.jsonl").read_text().splitlines() if line]


def save_summary(
    evidence: Path, root: Path, discarded: dict[str, Path], judge: Path | None
) -> None:
    """Compute counts that need the local per-item rows and save them next to the evidence."""
    runs = _runs(evidence)
    reach, usage, miss = {}, {}, {}
    for key, name in runs.items():
        rows = [row["payload"] for row in _items(root / name)]
        if key.startswith(("v1-", "mp-", "latency-")):
            reach[key] = {
                "n": len(rows),
                "planner": sum("plan" in row["trace"] for row in rows),
                "parts": sum(row.get("route_source") == "parts" for row in rows),
                "whole": sum(row.get("route_source") != "parts" for row in rows),
            }
            usage[key] = {
                "calls": statistics.mean(row.get("llm_calls") or 0 for row in rows),
                "input_tokens": statistics.mean(row.get("input_tokens") or 0 for row in rows),
                "output_tokens": statistics.mean(row.get("output_tokens") or 0 for row in rows),
            }
        if key.startswith("mp-") and key.endswith("-pp"):
            missed = [row for row in rows if "plan" not in row["trace"]]
            miss[key] = {
                "n": len(rows),
                "missed": len(missed),
                "for_store": sum("and also For " in row["item"]["question"] for row in missed),
            }
    gone = {}
    for key, path in discarded.items():
        rows = _items(path)
        gone[key] = {
            "n": len(rows),
            "dependency_unavailable": sum(
                row.get("handoff_reason") == "dependency_unavailable" for row in rows
            ),
        }
    data: dict[str, Any] = {
        "reach": reach,
        "usage": usage,
        "precheck_miss": miss,
        "discarded": gone,
    }
    if judge is not None:
        import csv

        with judge.open(encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        findings = [" ".join(json.loads(row["judge_findings"] or "[]")).casefold() for row in rows]
        data["judge"] = {
            "judged": sum(row["judge_flagged"] != "" for row in rows),
            "flagged": sum(row["judge_flagged"] == "true" for row in rows),
            # A keyword count, not a label: rows whose findings call a handoff unnecessary.
            "unnecessary_handoff_mentions": sum("unnecessary" in text for text in findings),
        }
    (evidence / "summary.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save-summary", action="store_true", help="read local rows, save JSON")
    parser.add_argument("--discarded", nargs="*", default=[], metavar="KEY=RUN_DIR")
    parser.add_argument("--judge-csv", type=Path)
    args = parser.parse_args(argv)
    if args.save_summary:
        discarded = {
            key: Path(path) for key, path in (entry.split("=", 1) for entry in args.discarded)
        }
        save_summary(EVIDENCE, RUNS, discarded, args.judge_csv)
    write_text(REPORT, render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
