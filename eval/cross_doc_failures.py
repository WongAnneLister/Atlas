"""Diagnose cross-document outcomes from saved full-graph runs, offline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.e2e_records import E2ERecord
from eval.e2e_runs import load_e2e
from support_agent.data.doc_models import write_text

RUN_ROOT = Path("eval/runs")
DEFAULT_RUNS = (
    RUN_ROOT / "e2e-test-20261117-266c1e85-legacy",
    RUN_ROOT / "smoke-test-20261121-c80a8668-ed86add9",
    RUN_ROOT / "smoke-test-20261121-b7d761af-dc9d2d85",
)
REPORT = Path("eval/reports/cross_doc_failures.md")
TOP_K = 5


def _top_gold(record: E2ERecord) -> set[str]:
    return set(record.item.gold_sections).intersection(record.retrieved_section_ids[:TOP_K])


def _format_values(values: list[str]) -> str:
    return ", ".join(f"`{value}`" for value in values) or "—"


def _gate(record: E2ERecord) -> str:
    gate = record.gate or {}
    passed = gate.get("passed")
    if not isinstance(passed, bool):
        return "—"
    outcome = "pass" if passed else "fail"
    reason = gate.get("reason")
    return f"{outcome} (`{reason}`)" if reason else outcome


def _item_row(record: E2ERecord) -> str:
    gold = record.item.gold_sections
    found = _top_gold(record)
    fields = [
        f"`{record.item.id}`",
        _format_values([record.path] if record.path else []),
        "yes" if "retrieve" in record.trace else "no",
        _format_values([section for section in gold if section in found]),
        _format_values([section for section in gold if section not in found]),
        _gate(record),
        _format_values([record.handoff_reason] if record.handoff_reason else []),
        _format_values(
            [value for value in (record.answer_status, record.answer_error_type) if value]
        ),
        "yes" if record.accepted else "no",
    ]
    return "| " + " | ".join(fields) + " |"


def run_results(records: list[E2ERecord]) -> list[str]:
    rejected = [record for record in records if not record.accepted]
    retrieved = [record for record in records if "retrieve" in record.trace]
    missing_counts = [
        len(record.item.gold_sections) - len(_top_gold(record))
        for record in rejected
        if "retrieve" in record.trace and not record.retrieval_error_type
    ]
    counts = {
        "Cross-document items": len(records),
        "Accepted": len(records) - len(rejected),
        "Rejected": len(rejected),
        "Reached knowledge retrieval": len(retrieved),
        "Reached knowledge retrieval with every gold section in the top 5": sum(
            len(_top_gold(record)) == len(record.item.gold_sections) for record in retrieved
        ),
        "Recorded gate passed": sum(
            (record.gate or {}).get("passed") is True for record in records
        ),
        "Rejected before knowledge retrieval": sum(
            "retrieve" not in record.trace for record in rejected
        ),
        "Rejected with exactly one gold section missing after retrieval": missing_counts.count(1),
        "Rejected with multiple gold sections missing after retrieval": sum(
            count > 1 for count in missing_counts
        ),
        "Rejected with a failed gate": sum(
            (record.gate or {}).get("passed") is False for record in rejected
        ),
        "Coverage marked a part unsupported": sum(
            record.answer_status == "insufficient_coverage" for record in rejected
        ),
        "Coverage relied on absence": sum(
            record.answer_status == "implied_by_absence" for record in rejected
        ),
        "Invalid quote or quote source": sum(
            record.answer_status == "invalid_evidence" for record in rejected
        ),
        "Dependency unavailable": sum(
            record.handoff_reason == "dependency_unavailable" for record in rejected
        ),
    }
    return [
        "| Outcome or observed pattern | Count |",
        "|---|---:|",
        *(f"| {label} | {count} |" for label, count in counts.items()),
        "",
        "| Item | Initial path | Reached knowledge retrieval | Gold in recorded top 5 "
        "| Gold absent from recorded top 5 | Gate | Handoff reason | Answer status and error "
        "| Accepted |",
        "|---|---|---|---|---|---|---|---|---|",
        *(_item_row(record) for record in sorted(records, key=lambda record: record.item.id)),
        "",
    ]


def render_report(paths: list[Path]) -> str:
    lines = [
        "# Cross-document failure analysis",
        "",
        "Generated offline by `make eval-cross-doc-failures` from saved per-item graph records. "
        "The smoke runs repeat test items, so counts are shown per run.",
        "",
        "Acceptance is the saved graph outcome. Section hits use the first five recorded ranks "
        "including repeated sections. The knowledge retrieval node can also run after a tool "
        "fallback. Missing-section counts use rejected rows that reached this node and have no "
        "recorded retrieval error. Failure patterns can overlap. "
        "A dash marks an empty or unavailable value.",
        "",
    ]
    for path in paths:
        metadata, records = load_e2e(path)
        cross_doc = [record for record in records if record.item.group == "cross_doc"]
        if not cross_doc:
            raise ValueError(f"{path} contains no cross_doc records")
        lines.extend(
            [
                f"## {path.name}",
                "",
                f"- Source `{path}`",
                f"- Git SHA `{metadata.git_sha}`",
                f"- Config hash `{metadata.config_hash}`",
                f"- Eval file hash `{metadata.eval_file_hash}`",
                f"- Corpus hash `{metadata.corpus_hash}`",
                f"- Recorded at {metadata.date} for split `{metadata.split}`",
                f"- Models `{json.dumps(metadata.models, sort_keys=True)}`",
                f"- Dataset versions `{json.dumps(metadata.dataset_versions, sort_keys=True)}`",
                "",
                *run_results(cross_doc),
            ]
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, action="append", help="saved run directory or JSONL")
    parser.add_argument("--output", type=Path, default=REPORT, help="Markdown report path")
    args = parser.parse_args()
    try:
        report = render_report(args.run or list(DEFAULT_RUNS))
    except (OSError, ValueError) as error:
        parser.error(str(error))
    write_text(args.output, report)


if __name__ == "__main__":
    main()
