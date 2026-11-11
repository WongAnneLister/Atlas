"""Validate paired coverage runs and compare acceptance under identical frozen inputs."""

from __future__ import annotations

import json
from pathlib import Path

from eval.coverage_eval import CoverageRecord
from eval.metrics import outcome_rates, percentile


def paired_lines(meta: dict, rows: list[CoverageRecord], baseline: Path) -> list[str]:
    lines = baseline.read_text().splitlines()
    old_meta = json.loads(lines[0])
    old = [CoverageRecord.model_validate_json(line) for line in lines[1:]]
    for key in (
        "inputs_hash",
        "config_hash",
        "split",
        "provider",
        "main_model",
        "model_options",
        "runtime",
    ):
        if meta[key] != old_meta[key]:
            raise ValueError(f"Coverage comparison changed {key}")
    for records in (old, rows):
        if len({r.case.id for r in records}) != len(records):
            raise ValueError("Coverage comparison contains duplicate items")
    if {r.case.id: r.case.model_dump() for r in old} != {
        r.case.id: r.case.model_dump() for r in rows
    }:
        raise ValueError("Coverage comparison changed frozen cases")
    output = [
        "",
        "## Paired original / candidate",
        "",
        f"- Original collection Git SHA: `{old_meta['git_sha']}`",
        f"- Original prompt hash: `{old_meta['prompt_hash']}`",
        f"- Original code hash: `{old_meta['code_hash']}`",
        f"- Original date: `{old_meta['date']}`",
        "",
        "| Run | Subset | False accept | False reject | Accepted | P50 | P95 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for label, records in (("Original", old), ("Candidate", rows)):
        for subset in sorted({r.case.subset for r in records}):
            chosen = [r for r in records if r.case.subset == subset]
            rates = outcome_rates([r.case.complete for r in chosen], [r.accepted for r in chosen])
            false_accept = (
                f"{rates.false_accept:.2%}" if any(not r.case.complete for r in chosen) else "n/a"
            )
            false_reject = (
                f"{rates.false_reject:.2%}" if any(r.case.complete for r in chosen) else "n/a"
            )
            latencies = [r.latency_s for r in chosen]
            output.append(
                f"| {label} | {subset} | {false_accept} | "
                f"{false_reject} | {rates.accepted_count} | "
                f"{percentile(latencies, 50):.4f}s | {percentile(latencies, 95):.4f}s |"
            )
    output += [
        "",
        "No paired failure is removed or retried for this comparison.",
        "Neither acceptance nor quote validation establishes factual answer accuracy.",
    ]
    return output
