"""Render the commit 23b policy version evidence from committed run records and saved outputs.

Every number comes from a run manifest and metrics file, a saved JSON file, or a report that
its own evaluator generated. Per-item rows stay local, so this report reads only committed files.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from eval.run_record import RUNS, MetricSummary, RunManifest, RunMetrics
from eval.stats import wilson_interval
from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.data.doc_models import write_text

EVIDENCE = RUNS / "policy-versions-23b"
REPORT = REPO_ROOT / "eval/reports/policy_versions.md"
# Run directories behind each table, in the order they are shown.
TIME_SENSITIVE = {
    ("dev", "off"): "time_sensitive-dev-20261122-cd121855-1f4299ba37644d5a9e674dd6b66be7ac",
    ("dev", "date"): "time_sensitive-dev-20261122-cd121855-b2787a95a19544389ffb667d1ed7e544",
    ("dev", "date_category"): (
        "time_sensitive-dev-20261122-cd121855-e088b5d57edb433eb1c90a2a4b527926"
    ),
    ("test", "off"): "time_sensitive-test-20261122-cd121855-8d29360c1abc43e6b212bfc6f486b1eb",
    ("test", "date"): "time_sensitive-test-20261122-cd121855-417e1ea18bcc4197b75f9d5e9e24693f",
    ("test", "date_category"): (
        "time_sensitive-test-20261122-cd121855-c85da09ec3b548ea90fefc47fdf45d7d"
    ),
}
RETRIEVAL = "retrieval-all-20261122-bed2ad57-084730753680"
REDTEAM = ("redteam-test-20261121-b7d761af-ec53deb3", "redteam-test-20261122-bed2ad57-cd88238b")
END_TO_END = "time_sensitive_e2e-dev-test-20261122-bed2ad57-8e3c5b60e8cf4f5f93fff542b72a98d5"
COMPARISONS = {
    "Time-sensitive test, filters off vs date_category": (
        "compare-time-sensitive-test-off-vs-date-category.md"
    ),
    "Time-sensitive dev, filters off vs date_category": (
        "compare-time-sensitive-dev-off-vs-date-category.md"
    ),
    "Red-team test, 21b baseline vs 23b": "compare-redteam-test.md",
}
# The committed reports before this evidence commit; refund reports have no run records.
BASELINE_REVISION = "bed2ad5"
SUMMARY_SECTIONS = {
    "eval/reports/refund_policy.md": "## Summary",
    "eval/reports/refund_decisions.md": "## Summary",
}


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


def _run_line(name: str, root: Path) -> str:
    manifest = _manifest(name, root)
    return (
        f"- `eval/runs/{name}`: SHA `{manifest.git_sha[:8]}`, dirty {manifest.dirty}, "
        f"config `{manifest.config_hash[:12]}`, models {manifest.models}"
    )


def _section(text: str, heading: str) -> list[str]:
    lines = text.splitlines()
    start = lines.index(heading) + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
    return [line for line in lines[start:end] if line.startswith("|")]


def _deltas(path: Path) -> list[str]:
    return _section(path.read_text(encoding="utf-8"), "## Metric deltas (B minus A)")


def index_lines(evidence: Path) -> list[str]:
    plan = json.loads((evidence / "index-plan.json").read_text(encoding="utf-8"))
    build = json.loads((evidence / "index-build.json").read_text(encoding="utf-8"))
    before = json.loads((evidence / "index-status.before.json").read_text(encoding="utf-8"))
    release = (evidence / "index-release.md").read_text(encoding="utf-8").splitlines()
    return [
        "## Data and index",
        "",
        f"- Alias before 23b: `{before['alias']}`; registry drift: {before['drift']}.",
        f"- Index plan: mode `{plan['mode']}`; {len(plan['added'])} added, "
        f"{len(plan['changed'])} changed, {len(plan['deleted'])} deleted, "
        f"{len(plan['unchanged'])} unchanged sections.",
        *(f"  - added `{section}`" for section in plan["added"]),
        f"- Build `{build['build_id']}`: mode `{build['mode']}`, {build['chunk_count']} chunks, "
        f"{build['embedded_chunks']} embedded, {build['elapsed_s']:.0f} s.",
        "- Release check (saved output `index-release.md`, eval_v1 dev + smoke, paired):",
        f"  - Decision: {release[0].split(' — ')[-1]}",
        *(f"  {line}" for line in release if line.startswith(("- gate", "- hit", "- no", "- rr"))),
        "",
    ]


def time_sensitive_lines(root: Path) -> list[str]:
    metrics = ("version_hit_at_5", "wrong_version_at_5", "gate_pass", "filters_applied")
    lines = [
        "## Time-sensitive retrieval (eval_v2, no LLM)",
        "",
        "Per-path rows are in `eval/reports/time_sensitive.md`. Test is the result; dev is shown.",
        "Counts show 95% Wilson intervals.",
        "",
        "| Split | Filters | " + " | ".join(metrics) + " |",
        "|---|---|" + "---|" * len(metrics),
    ]
    for (split, filters), name in TIME_SENSITIVE.items():
        values = _metrics(name, root)
        lines.append(
            f"| {split} | {filters} | "
            + " | ".join(_cell(values.get(metric)) for metric in metrics)
            + " |"
        )
    lines.append("")
    lines.extend(_run_line(name, root) for name in TIME_SENSITIVE.values())
    return [*lines, ""]


def comparison_lines(evidence: Path) -> list[str]:
    lines = ["## Paired comparisons (`make eval-compare`)", ""]
    for title, file in COMPARISONS.items():
        lines.extend(
            [f"### {title}", "", f"Source: `{(evidence / file).relative_to(REPO_ROOT)}`", ""]
        )
        lines.extend([*_deltas(evidence / file), ""])
    return lines


def retrieval_lines(root: Path) -> list[str]:
    report = (REPO_ROOT / "eval/reports/retrieval.md").read_text(encoding="utf-8").splitlines()
    rows = [
        line
        for line in report
        if line.startswith("| hybrid_rerank_filters_") and "| overall |" in line
    ]
    header = next(line for line in report if line.startswith("| Mode | Group |"))
    return [
        "## eval_v1 retrieval with filters (`make eval-retrieval SPLIT=all`)",
        "",
        "Overall rows for dev, then test, from `eval/reports/retrieval.md`.",
        "",
        header,
        _rule(header),
        *rows,
        "",
        _run_line(RETRIEVAL, root),
        "",
    ]


def _rule(header: str) -> str:
    return "|" + "---|" * (header.count("|") - 1)


def baseline_lines(report: str, heading: str) -> list[str]:
    from eval.run_record import git

    current = (REPO_ROOT / report).read_text(encoding="utf-8")
    before = git("show", f"{BASELINE_REVISION}:{report}")
    return [
        f"### `{report}`",
        "",
        f"Before (committed at `{BASELINE_REVISION}`), not a paired run:",
        "",
        *_section(before, heading),
        "",
        "After (23b):",
        "",
        *_section(current, heading),
        "",
    ]


def holdout_lines(evidence: Path) -> list[str]:
    data = json.loads((evidence / "holdout-dates.json").read_text(encoding="utf-8"))
    return [
        f"- Window holdout: {data['orders']} delivered orders dated {data['first']} to "
        f"{data['last']}. Orders whose expected answer depends on the policy version in force "
        f"on the order date: {len(data['changed'])}.",
        "",
    ]


def end_to_end_lines(root: Path) -> list[str]:
    values = _metrics(END_TO_END, root)
    return [
        "## Refund path end to end (real models)",
        "",
        "Rows and requests are in `eval/reports/time_sensitive_e2e.md`.",
        "",
        "| Metric | Count [95% Wilson] |",
        "|---|---|",
        *(f"| {name} | {_cell(summary)} |" for name, summary in sorted(values.items())),
        "",
        "Missed gold citations and notices are rows where the decision model asked for a human,",
        "so no policy was cited; none cites the wrong version.",
        "",
        _run_line(END_TO_END, root),
        "",
    ]


def redteam_lines(root: Path) -> list[str]:
    lines = ["## Red-team (redteam_v2 test)", "", "| Run | attack_success | wrongly_blocked |"]
    lines.append("|---|---|---|")
    for name in REDTEAM:
        values = _metrics(name, root)
        lines.append(
            f"| `{name}` | {_cell(values.get('attack_success'))} | "
            f"{_cell(values.get('wrongly_blocked'))} |"
        )
    return [*lines, "", *(_run_line(name, root) for name in REDTEAM), ""]


def integration_lines(evidence: Path) -> list[str]:
    text = (evidence / "integration.txt").read_text(encoding="utf-8").splitlines()
    return [
        "## Integration tests (saved pytest summaries)",
        "",
        *(f"- {line}" for line in text),
        "",
    ]


def render(evidence: Path = EVIDENCE, root: Path = RUNS) -> str:
    lines = [
        "# Policy versions — commit 23b evidence",
        "",
        "Generated by `make eval-policy-versions-report` from committed run records and saved",
        f"outputs in `{evidence.relative_to(REPO_ROOT)}`. Do not edit by hand.",
        "",
        "Limits: two synthetic historical sections (returns and price adjustment, changing",
        "on 2026-09-01); 4 dated refund orders per split; eval_v2 time-sensitive labels are",
        "unreviewed.",
        "",
        *index_lines(evidence),
        *time_sensitive_lines(root),
        *comparison_lines(evidence),
        *retrieval_lines(root),
        "## Refund policy retrieval and decisions",
        "",
        *holdout_lines(evidence),
        *(
            line
            for report, heading in SUMMARY_SECTIONS.items()
            for line in baseline_lines(report, heading)
        ),
        *end_to_end_lines(root),
        *redteam_lines(root),
        *integration_lines(evidence),
    ]
    return "\n".join(lines).rstrip("\n") + "\n"


def save_holdout(settings: Settings, output: Path) -> dict[str, Any]:
    """Record which window-holdout expectations depend on the order date (reads orders only)."""
    from eval.refund_decision_eval import holdout_orders
    from support_agent.data.policy_versions import load_versions
    from support_agent.graph.refund_decision import WINDOW
    from support_agent.orders.service import OrderService

    versions = load_versions(settings.policy_versions)
    (policy,) = (e for e in versions.entries if e.base_section_id.startswith("returns."))
    # The current section's purchase window, parsed as the evaluator parses it.
    (current,) = (
        int(d) for d, anchor in WINDOW.findall(policy.old.find) if anchor.lower() == "purchase"
    )
    rows = holdout_orders(OrderService(settings=settings.orders), settings, versions)
    changed = []
    for order, expected in rows:
        days = (settings.orders.today - order.order_date).days
        if expected != ({"yes"} if days <= current else {"no"}):
            changed.append(
                {"order_id": order.order_id, "order_date": str(order.order_date), "days": days}
            )
    dates = sorted(str(order.order_date) for order, _ in rows)
    data = {"orders": len(rows), "first": dates[0], "last": dates[-1], "changed": changed}
    output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save-holdout", action="store_true", help="read orders, save JSON")
    args = parser.parse_args(argv)
    if args.save_holdout:
        save_holdout(get_settings(), EVIDENCE / "holdout-dates.json")
    write_text(REPORT, render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
