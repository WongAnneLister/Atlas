"""Compare full-graph runs before and after the store-scope check.

Each pair of runs covers identical frozen items. The cross-store holdout v2 was frozen
before the check was written; holdout v1 and the old test split are already-seen
regression evidence.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from eval.e2e_records import E2EMetadata, E2ERecord
from eval.gate_round3 import rate_cell
from support_agent.config import REPO_ROOT, StoreScopeSettings, get_settings
from support_agent.data.doc_models import write_text
from support_agent.retrieval.scope import requested_stores, section_store

REPORT = Path("eval/reports/store_scope.md")


@dataclass(frozen=True)
class Pair:
    label: str
    before: Path
    after: Path
    role: str


PAIRS = [
    Pair(
        "Cross-store holdout v2",
        Path("eval/runs/store-v2-before.jsonl"),
        Path("eval/runs/store-v2-after.jsonl"),
        "fresh; frozen before this change",
    ),
    Pair(
        "Near-miss holdout v1",
        Path("eval/runs/round3-holdout-after.jsonl"),
        Path("eval/runs/store-v1-after.jsonl"),
        "seen in gate round three",
    ),
    Pair(
        "Old test split",
        Path("eval/runs/store-test-before.jsonl"),
        Path("eval/runs/store-test-after.jsonl"),
        "seen; regression evidence",
    ),
]


def load_run(path: Path) -> tuple[E2EMetadata, dict[str, E2ERecord]]:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    metadata = E2EMetadata.model_validate_json(lines[0])
    records = [E2ERecord.model_validate_json(line) for line in lines[1:]]
    return metadata, {record.item.id: record for record in records}


def family(record: E2ERecord) -> str:
    try:
        return str(json.loads(record.item.notes)["family"])
    except (ValueError, KeyError, TypeError):
        return record.item.group


def outcome_lines(records: dict[str, E2ERecord]) -> tuple[str, str]:
    no_answer = [r for r in records.values() if not r.item.answerable]
    answerable = [r for r in records.values() if r.item.answerable]
    fa = rate_cell(sum(r.accepted for r in no_answer), len(no_answer)) if no_answer else "n/a"
    fr = (
        rate_cell(sum(not r.accepted for r in answerable), len(answerable)) if answerable else "n/a"
    )
    return fa, fr


def change_cause(before: E2ERecord, after: E2ERecord, scope: StoreScopeSettings) -> str:
    """Attribute an outcome change: only other-store evidence lets the filter matter."""
    if before.path != after.path:
        return "route changed"
    stores = requested_stores(before.item.question, scope)
    other = [
        sid
        for sid in before.retrieved_section_ids
        if len(stores) == 1 and section_store(sid, scope) not in (None, *stores)
    ]
    if other:
        return "filter removed other-store evidence"
    return "same path, filter had nothing to remove"


def section(pair: Pair, scope: StoreScopeSettings) -> list[str]:
    root = REPO_ROOT
    if not (root / pair.before).exists() or not (root / pair.after).exists():
        return [f"## {pair.label}", "", "Not measured: a run file is missing.", ""]
    meta_a, before = load_run(root / pair.before)
    meta_b, after = load_run(root / pair.after)
    if set(before) != set(after):
        raise ValueError(f"{pair.label}: runs cover different items")
    fa_a, fr_a = outcome_lines(before)
    fa_b, fr_b = outcome_lines(after)
    lines = [
        f"## {pair.label}",
        "",
        f"- Role: {pair.role}",
        f"- Before: `{pair.before.as_posix()}` at `{meta_a.git_sha}` "
        f"(code `{(meta_a.code_hash or 'n/a')[:12]}`), {meta_a.date}",
        f"- After: `{pair.after.as_posix()}` at `{meta_b.git_sha}` "
        f"(code `{(meta_b.code_hash or 'n/a')[:12]}`), {meta_b.date}",
        f"- Models: {json.dumps(meta_b.models, sort_keys=True)}",
        "",
        "| Outcome | Before | After |",
        "|---|---:|---:|",
        f"| False accept (no-answer accepted) | {fa_a} | {fa_b} |",
        f"| False reject (answerable not accepted) | {fr_a} | {fr_b} |",
        "",
    ]
    families = sorted({family(r) for r in before.values() if not r.item.answerable})
    if families:
        lines += ["| No-answer family | Items | Accepted before | Accepted after |"]
        lines += ["|---|---:|---:|---:|"]
        for name in families:
            ids = [i for i, r in before.items() if not r.item.answerable and family(r) == name]
            lines.append(
                f"| {name} | {len(ids)} | {sum(before[i].accepted for i in ids)} | "
                f"{sum(after[i].accepted for i in ids)} |"
            )
        lines.append("")
    changed = [i for i in before if before[i].accepted != after[i].accepted]
    causes = {i: change_cause(before[i], after[i], scope) for i in changed}
    lines += ["| Cause of change | Now accepted | Now rejected |", "|---|---:|---:|"]
    for cause in sorted(set(causes.values())):
        ids = [i for i in changed if causes[i] == cause]
        lines.append(
            f"| {cause} | {sum(after[i].accepted for i in ids)} | "
            f"{sum(not after[i].accepted for i in ids)} |"
        )
    lines += ["", "| Changed item | Group | Path | Accepted | Handoff after | Cause |"]
    lines += ["|---|---|---|---|---|---|"]
    lines += [
        f"| {i} | {after[i].item.group} | {before[i].path} to {after[i].path} | "
        f"{before[i].accepted} to {after[i].accepted} | {after[i].handoff_reason or '-'} | "
        f"{causes[i]} |"
        for i in sorted(changed)
    ] or ["| none | | | | | |"]
    still = [i for i, r in after.items() if not r.item.answerable and r.accepted]
    if still:
        lines += ["", "No-answer items still accepted after the change:", ""]
        lines += [f"- `{i}` ({family(after[i])}, path {after[i].path})" for i in sorted(still)]
    return [*lines, ""]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    lines = [
        "# Store-scope check",
        "",
        "Generated by `make eval-store-scope`. Questions that name exactly one store",
        "only see that store's sections plus store-neutral ones (the product catalog).",
        "Only holdout v2 is unseen; the other sets show regressions and side effects.",
        "",
    ]
    scope = get_settings().retrieval.store_scope
    for pair in PAIRS:
        lines += section(pair, scope)
    lines += [
        "## Limits",
        "",
        "Holdout items are agent-authored and unreviewed; holdouts have no answerable items.",
        "Store detection matches store names in the question text only.",
        "Run files record model names, not the API endpoint used.",
        "Before and after runs are separate model calls; some changes can be model noise.",
        "A change is attributed to the filter only when the before-run evidence held",
        "another store's section; route changes and unchanged evidence are run-to-run noise.",
        "Four old-test after rows that failed during an SSH tunnel drop were removed and re-run.",
    ]
    write_text(REPO_ROOT / REPORT, "\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
