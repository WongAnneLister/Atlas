"""Render the commit 25b claim grounding evidence from committed records and saved outputs.

Every number comes from a run manifest or metrics file, a verifier prediction file, a paired
comparison or gate report written by its own command, or `summary.json`, which
`--save-summary` computes from the local per-item rows and the local claim set.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from eval.run_record import RUNS, MetricSummary, RunManifest, RunMetrics
from eval.stats import wilson_interval
from support_agent.config import REPO_ROOT, get_settings
from support_agent.data.doc_models import write_text

EVIDENCE = RUNS / "claim-grounding-25b"
REPORT = REPO_ROOT / "eval/reports/claim_grounding.md"
E2E_METRICS = ("false_accept", "false_reject", "pass_rate", "full_answer_rate", "citation_validity")
MULTIPART_METRICS = (
    "full_answer_rate",
    "answered_part_correct",
    "unanswerable_part_handed_off",
    "noanswer_false_accept",
)
COMPARISONS = {
    "eval_v1 test, grounding off vs on": "compare-v1-test.md",
    "eval_v1 dev, grounding off vs on": "compare-v1-dev.md",
    "multipart test, grounding off vs on": "compare-mp-test.md",
    "Latency, smoke set run alone, grounding off vs on": "compare-latency.md",
}


def _runs(evidence: Path) -> dict[str, str]:
    runs: dict[str, str] = json.loads((evidence / "runs.json").read_text(encoding="utf-8"))
    return runs


def _manifest(name: str, root: Path) -> RunManifest:
    return RunManifest.model_validate_json((root / name / "manifest.json").read_bytes())


def _metrics(name: str, root: Path) -> dict[str, MetricSummary]:
    return RunMetrics.model_validate_json((root / name / "metrics.json").read_bytes()).metrics


def _rate(count: int, n: int) -> str:
    if n == 0:
        return "—"
    wilson = wilson_interval(count, n, get_settings().eval.stats.alpha)
    return f"{count}/{n} [{wilson.low:.0%}, {wilson.high:.0%}]"


def _cell(summary: MetricSummary | None) -> str:
    if summary is None:
        return "—"
    if summary.count is None:
        interval = summary.interval
        return f"{interval.point:.4f} [{interval.low:.4f}, {interval.high:.4f}]"
    return _rate(summary.count, summary.n)


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


def verifier_lines(data: dict[str, Any]) -> list[str]:
    lines = [
        "## Verifier on the frozen claim set (`claims_v1`)",
        "",
        "Real-claim labels are **model drafts not yet reviewed by the author**; synthetic",
        "claims are unsupported by construction. Recall is for the `unsupported` class.",
        "",
        "| Split | Group | Claims | Flagged unsupported | Recall on unsupported | "
        "Supported claims wrongly flagged |",
        "|---|---|---:|---:|---|---|",
    ]
    for row in data["verifier"]:
        lines.append(
            f"| {row['split']} | {row['group']} | {row['n']} | {row['flagged']} | "
            f"{_rate(row['tp'], row['positives'])} | {_rate(row['fp'], row['negatives'])} |"
        )
    lines.extend(["", "Verdict reasons (test):", ""])
    lines.extend(f"- `{reason}`: {count}" for reason, count in data["reasons"]["test"].items())
    lines.extend(
        [
            "",
            "Drafted-unsupported real claims the verifier accepted (test), by kind:",
            "",
            *(f"- {kind}: {count}" for kind, count in data["missed_kinds"].items()),
            "",
        ]
    )
    return lines


def e2e_lines(runs: dict[str, str], root: Path) -> list[str]:
    lines = ["## eval_v1 (full graph)", ""]
    for split in ("test", "dev"):
        header = "| Grounding | " + " | ".join(E2E_METRICS) + " |"
        lines.extend([f"### {split}", "", header, _rule(header)])
        for config in ("off", "on"):
            values = _metrics(runs[f"v1-{split}-{config}"], root)
            lines.append(
                f"| {config} | " + " | ".join(_cell(values.get(m)) for m in E2E_METRICS) + " |"
            )
        lines.append("")
    return lines


def multipart_lines(runs: dict[str, str], root: Path) -> list[str]:
    header = "| Split | Grounding | " + " | ".join(MULTIPART_METRICS) + " |"
    lines = ["## Multipart set (overall)", "", header, _rule(header)]
    for split in ("test", "dev"):
        for config in ("off", "on"):
            values = _metrics(runs[f"mp-{split}-{config}"], root)
            lines.append(
                f"| {split} | {config} | "
                + " | ".join(_cell(values.get(m)) for m in MULTIPART_METRICS)
                + " |"
            )
    return [*lines, ""]


def removal_lines(data: dict[str, Any]) -> list[str]:
    lines = [
        "## Claims checked and removed in the full graph (grounding on)",
        "",
        "| Run | Claims checked | Removed | Removal reasons | Grounding handoffs |",
        "|---|---:|---:|---|---:|",
    ]
    for key, row in data["removals"].items():
        reasons = ", ".join(f"{k} {v}" for k, v in row["reasons"].items()) or "—"
        lines.append(
            f"| {key} | {row['claims']} | {row['removed']} | {reasons} | {row['low_grounding']} |"
        )
    return [*lines, ""]


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
    text = (evidence / "gate.md").read_text(encoding="utf-8").splitlines()
    lines = [
        "## Release gate (knowledge smoke + red-team smoke)",
        "",
        f"- {text[0].lstrip('# ')}",
        "- The gate baseline predates the local Milvus copy and the rerank cache, so its",
        "  latency rows do not measure grounding; the smoke latency comparison above does.",
        "",
    ]
    previous = False
    for line in text[1:]:
        table = line.startswith("|")
        if table:
            lines.append(line)
        elif previous:
            lines.append("")
        previous = table
    return [*lines, ""]


def render(evidence: Path = EVIDENCE, root: Path = RUNS) -> str:
    runs = _runs(evidence)
    data: dict[str, Any] = json.loads((evidence / "summary.json").read_text(encoding="utf-8"))
    lines = [
        "# Claim grounding — commit 25b evidence",
        "",
        "Generated by `make eval-claim-grounding-report` from committed run records and saved",
        f"outputs in `{evidence.relative_to(REPO_ROOT)}`. Do not edit by hand.",
        "",
        "Real models; index build `4aece1a3` on the local Milvus copy; planning and partial",
        "answers on in every run, so only `grounding.enabled` differs. Dev was used for review;",
        "the one dev fix (`07cf8f5`, one verbatim quote per fact) came before every run here.",
        "Collection used `--workers 3` and the rerank cache except the gate smoke and the",
        "latency runs, which ran one item at a time; only those latencies are comparable.",
        "",
        *provenance_lines(runs, root),
        *verifier_lines(data),
        *e2e_lines(runs, root),
        *multipart_lines(runs, root),
        *removal_lines(data),
        *comparison_lines(evidence),
        *gate_lines(evidence),
    ]
    return "\n".join(lines).rstrip("\n") + "\n"


def _items(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (path / "items.jsonl").read_text().splitlines() if line]


def _kind(claim: str) -> str:
    text = claim.casefold()
    if text.startswith("yes") or text.startswith("no"):
        return "leading yes/no not stated in the source"
    if "source" in text:
        return "statement about the sources"
    return "other"


def save_summary(evidence: Path, root: Path, predictions: dict[str, Path]) -> None:
    """Compute claim and removal counts from local rows, predictions and the claim set."""
    from eval.build_claims import read_claims

    items = {item.id: item for item in read_claims()}
    verifier: list[dict[str, Any]] = []
    reasons: dict[str, dict[str, int]] = {}
    missed: Counter[str] = Counter()
    for split, path in predictions.items():
        run = json.loads(path.read_text(encoding="utf-8"))
        verdicts = {row["id"]: row["verdict"] for row in run["predictions"]}
        why = json.loads(path.with_suffix(".reasons.json").read_text(encoding="utf-8"))
        reasons[split] = dict(sorted(Counter(r.split(":")[0] for r in why.values()).items()))
        for group in ("real", "synthetic"):
            rows = [items[i] for i in verdicts if items[i].group == group]
            positive = [r for r in rows if group == "synthetic" or r.label == "unsupported"]
            negative = [r for r in rows if r not in positive]
            flagged = {r.id for r in rows if verdicts[r.id] != "supported"}
            verifier.append(
                {
                    "split": split,
                    "group": group,
                    "n": len(rows),
                    "flagged": len(flagged),
                    "tp": sum(r.id in flagged for r in positive),
                    "positives": len(positive),
                    "fp": sum(r.id in flagged for r in negative),
                    "negatives": len(negative),
                }
            )
            if split == "test" and group == "real":
                missed.update(_kind(r.claim) for r in positive if r.id not in flagged)
    removals = {}
    for key, name in _runs(evidence).items():
        if not key.endswith("-on"):
            continue
        records = _items(root / name)
        claims = [c for record in records for c in (record["payload"].get("claims") or [])]
        removed = [c for c in claims if c.get("removed")]
        removals[key] = {
            "claims": len(claims),
            "removed": len(removed),
            # A supported claim is removed only because its part's main claim failed.
            "reasons": dict(
                Counter(
                    "withdrawn with its part"
                    if c.get("verdict") == "supported"
                    else c.get("reason", "").split(":")[0]
                    for c in removed
                )
            ),
            "low_grounding": sum(
                record.get("handoff_reason") == "low_grounding" for record in records
            ),
        }
    data = {
        "verifier": verifier,
        "reasons": reasons,
        "missed_kinds": dict(missed),
        "removals": removals,
    }
    (evidence / "summary.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save-summary", action="store_true")
    parser.add_argument("--predictions", nargs="*", default=[], metavar="SPLIT=FILE")
    args = parser.parse_args(argv)
    if args.save_summary:
        files = {key: Path(path) for key, path in (p.split("=", 1) for p in args.predictions)}
        save_summary(EVIDENCE, RUNS, files)
    write_text(REPORT, render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
