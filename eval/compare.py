"""Compare two e2e JSONL runs and identify changed item outcomes."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from eval.e2e_records import E2EMetadata, E2ERecord
from eval.metrics import outcome_rates
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("a", type=Path)
    parser.add_argument("b", type=Path)
    parser.add_argument("--output", type=Path, default=Path("eval/reports/e2e_compare.md"))
    args = parser.parse_args(argv)
    meta_a, records_a = load_run(REPO_ROOT / args.a)
    meta_b, records_b = load_run(REPO_ROOT / args.b)
    diff = compare_runs(records_a, records_b)
    lines = [
        "# End-to-end run comparison",
        "",
        f"- Run A Git SHA: `{meta_a.git_sha}`",
        f"- Run A config hash: `{meta_a.config_hash}`",
        f"- Run A eval file hash: `{meta_a.eval_file_hash}`",
        f"- Run A split/date: {meta_a.split} / {meta_a.date}",
        f"- Run A models: `{meta_a.models}`",
        f"- Run B Git SHA: `{meta_b.git_sha}`",
        f"- Run B config hash: `{meta_b.config_hash}`",
        f"- Run B eval file hash: `{meta_b.eval_file_hash}`",
        f"- Run B split/date: {meta_b.split} / {meta_b.date}",
        f"- Run B models: `{meta_b.models}`",
        f"- Shared items: {diff['shared_items']}",
        f"- Only in A: {len(diff['only_a'])}",
        f"- Only in B: {len(diff['only_b'])}",
        "",
        "## Metric deltas (B minus A)",
        "",
        "| Metric | A | B | Delta |",
        "|---|---:|---:|---:|",
        *[
            f"| {name.replace('_', ' ').title()} | {diff['rates']['a'][name]:.2%} | "
            f"{diff['rates']['b'][name]:.2%} | {diff['deltas'][name]:+.2%} |"
            for name in ("false_accept", "false_reject", "pass_rate")
        ],
        "",
        "| Item | Accepted A | Accepted B | Handoff A | Handoff B |",
        "|---|---:|---:|---|---|",
    ]
    lines.extend(
        f"| {row['id']} | {row['accepted_a']} | {row['accepted_b']} | "
        f"{row['handoff_a']} | {row['handoff_b']} |"
        for row in diff["changed"]
    )
    write_text(REPO_ROOT / args.output, "\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
