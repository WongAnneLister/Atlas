"""Compare paired observations from saved eval runs."""

from __future__ import annotations

import argparse
from dataclasses import replace
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from eval.e2e_records import E2EMetadata, E2ERecord
from eval.e2e_runs import load_e2e, prepare_e2e
from eval.gate import load_rules
from eval.legacy_pairing import rows_for_legacy_core
from eval.metrics import outcome_rates
from eval.paired import Comparison, MetricRule, compare, comparison_lines
from eval.redteam_models import CATEGORIES
from eval.run_record import Run, read_run
from support_agent.config import REPO_ROOT
from support_agent.data.doc_models import write_text


def load_run(path: Path) -> tuple[E2EMetadata, dict[str, E2ERecord]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"Empty run file: {path}")
    metadata = E2EMetadata.model_validate_json(lines[0])
    records = {
        record.item.id: record
        for line in lines[1:]
        if line.strip()
        for record in [E2ERecord.model_validate_json(line)]
    }
    return metadata, records


def compare_runs(a: dict[str, E2ERecord], b: dict[str, E2ERecord]) -> dict[str, Any]:
    shared = sorted(a.keys() & b.keys())
    changed = [
        {
            "id": item_id,
            "accepted_a": a[item_id].accepted,
            "accepted_b": b[item_id].accepted,
            "handoff_a": a[item_id].handoff_reason,
            "handoff_b": b[item_id].handoff_reason,
        }
        for item_id in shared
        if (a[item_id].accepted, a[item_id].handoff_reason)
        != (b[item_id].accepted, b[item_id].handoff_reason)
    ]
    rates: dict[str, dict[str, float]] = {}
    deltas: dict[str, float] = {}
    for label, run in (("a", a), ("b", b)):
        selected = [run[item_id] for item_id in shared]
        metrics = outcome_rates(
            [record.item.answerable for record in selected],
            [record.accepted for record in selected],
        )
        rates[label] = {
            "false_accept": metrics.false_accept,
            "false_reject": metrics.false_reject,
            "pass_rate": metrics.pass_rate,
        }
    for name in ("false_accept", "false_reject", "pass_rate"):
        deltas[name] = rates["b"][name] - rates["a"][name]
    return {
        "shared_items": len(shared),
        "only_a": sorted(a.keys() - b.keys()),
        "only_b": sorted(b.keys() - a.keys()),
        "changed": changed,
        "rates": rates,
        "deltas": deltas,
    }


def _read(path: Path, reference: Run | None) -> Run:
    if path.is_dir():
        return read_run(path)
    if reference is None or reference.manifest.kind in {"e2e", "smoke"}:
        return prepare_e2e(*load_e2e(path))
    if reference.manifest.kind == "judge":
        from eval.judge import project_judge, read_review

        items = project_judge(read_review(path))
    else:
        items = rows_for_legacy_core(path, reference)
    metadata = reference.manifest.model_copy(
        update={
            "git_sha": "unavailable",
            "config_hash": "unavailable",
            "datasets": {},
            "models": {},
        }
    )
    return reference.model_copy(update={"items": items, "manifest": metadata})


def _rules(before: Run, after: Run) -> dict[str, MetricRule]:
    settings = load_rules()
    a = {name for row in before.items for name in row.metrics}
    b = {name for row in after.items for name in row.metrics}
    rules = {}
    for name in sorted(a & b):
        if name in settings.metrics:
            rules[name] = settings.metrics[name]
            continue
        before_stat = before.metrics.statistics.get(name, "mean")
        after_stat = after.metrics.statistics.get(name, "mean")
        if before_stat != after_stat:
            raise ValueError(f"Incompatible statistics for {name}")
        values = [
            row.metrics[name] for run in (before, after) for row in run.items if name in row.metrics
        ]
        lower = any(fnmatch(name, pattern) for pattern in settings.comparison_lower_is_better)
        rules[name] = MetricRule(
            direction="lower" if lower else "higher",
            test="mcnemar" if all(type(value) is bool for value in values) else "bootstrap",
            statistic=before_stat,
        )
    return rules


def _redteam_categories(before: Run, after: Run, rules: dict[str, MetricRule]) -> list[Comparison]:
    results = []
    for category in CATEGORIES:
        a, b = (
            run.model_copy(update={"items": [row for row in run.items if row.group == category]})
            for run in (before, after)
        )
        if {row.id for row in a.items}.isdisjoint(row.id for row in b.items):
            continue
        results.extend(
            replace(result, name=f"{category}/{result.name}") for result in compare(a, b, rules)
        )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("a", type=Path)
    parser.add_argument("b", type=Path)
    parser.add_argument("--output", type=Path, default=Path("eval/reports/e2e_compare.md"))
    args = parser.parse_args(argv)
    a, b = REPO_ROOT / args.a, REPO_ROOT / args.b
    reference = next((read_run(path) for path in (a, b) if path.is_dir()), None)
    before, after = _read(a, reference), _read(b, reference)
    ids_a, ids_b = ({row.id for row in run.items} for run in (before, after))
    rules = _rules(before, after)
    results = compare(before, after, rules)
    if not results:
        raise ValueError("Runs have no shared metrics to compare")
    if before.manifest.kind == after.manifest.kind == "redteam":
        results.extend(_redteam_categories(before, after, rules))

    lines = ["# Eval run comparison", ""]
    for label, path, run in (("A", args.a, before), ("B", args.b, after)):
        meta = run.manifest
        lines.extend(
            [
                f"- Run {label}: `{path}`",
                f"- Run {label} Git SHA: `{meta.git_sha}`",
                f"- Run {label} config hash: `{meta.config_hash}`",
                f"- Run {label} datasets: `{meta.datasets}`",
                f"- Run {label} split: {meta.split}",
                f"- Run {label} models: `{meta.models}`",
            ]
        )
    lines.extend(
        [
            f"- Shared items: {len(ids_a & ids_b)}",
            f"- Only in A: {len(ids_a - ids_b)}",
            f"- Only in B: {len(ids_b - ids_a)}",
            "",
            "## Metric deltas (B minus A)",
            "",
            *comparison_lines(results),
            "",
        ]
    )
    if before.manifest.kind in {"e2e", "smoke"} and after.manifest.kind in {"e2e", "smoke"}:
        _, records_a = load_e2e(a)
        _, records_b = load_e2e(b)
        changes = compare_runs(
            {row.item.id: row for row in records_a}, {row.item.id: row for row in records_b}
        )
        lines.extend(
            [
                "| Item | Accepted A | Accepted B | Handoff A | Handoff B |",
                "|---|---:|---:|---|---|",
            ]
        )
        lines.extend(
            f"| {row['id']} | {row['accepted_a']} | {row['accepted_b']} | "
            f"{row['handoff_a']} | {row['handoff_b']} |"
            for row in changes["changed"]
        )
    write_text(REPO_ROOT / args.output, "\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
