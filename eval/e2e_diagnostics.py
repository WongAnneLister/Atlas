"""Separate observed dependency and answer-stage failures without guessing legacy status."""

from collections import Counter

from eval.e2e_records import E2ERecord


def diagnostic_lines(records: list[E2ERecord]) -> list[str]:
    counts = {
        "Classification call failed": sum(r.classification_failed is True for r in records),
        "Retrieval call failed": sum(r.retrieval_error_type is not None for r in records),
        "Answer model failed": sum(r.answer_status == "model_error" for r in records),
        "Gate rejected without retrieval error": sum(
            r.classification_failed is not None
            and r.path == "B"
            and r.gate is not None
            and not r.gate.get("passed")
            and not r.retrieval_error_type
            for r in records
        ),
        "Coverage incomplete": sum(r.answer_status == "insufficient_coverage" for r in records),
        "Answer only implied by absence": sum(
            r.answer_status == "implied_by_absence" for r in records
        ),
        "Invalid answer output": sum(r.answer_status == "invalid_output" for r in records),
        "Invalid evidence quotes": sum(r.answer_status == "invalid_evidence" for r in records),
        "Invalid citations": sum(r.answer_status == "invalid_citation" for r in records),
        "Diagnostic fields unavailable": sum(r.classification_failed is None for r in records),
    }
    lines = [
        "",
        "## Failure diagnostics",
        "",
        "Counts can overlap. Missing fields in older runs remain unknown.",
        "Gate rejection without retrieval error is measured only on instrumented knowledge rows.",
        "",
        "| Observed condition | Items |",
        "|---|---:|",
        *[f"| {name} | {value} |" for name, value in counts.items()],
        "",
        "### Rejected answerable items",
        "",
        "| Path / handoff / answer status | Items |",
        "|---|---:|",
    ]
    counts_by_reason = Counter(
        f"{r.path} / {r.handoff_reason} / {r.answer_status or 'unknown'}"
        for r in records
        if r.item.answerable and not r.accepted
    )
    lines.extend(f"| {name} | {count} |" for name, count in sorted(counts_by_reason.items()))
    return lines
