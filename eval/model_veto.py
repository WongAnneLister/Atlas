"""Model-number veto: gate decisions with and without it, offline on cached retrieval.

The specific-term veto passes when any named term hits, so a common word such as
"USB" can stand in for a model the corpus does not have. The model-number veto also
requires one of the named model numbers to appear in the top chunks. Both settings
rescore the same cached snapshots from `make eval-chunking-ab`, so only the gate
differs; each picks its own threshold on dev with the midpoint rule. No LLM calls.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from eval.chunking_ab import INDEXES, LABELS, SETS, cache_path, index_settings, passes, set_items
from eval.gate_round3 import rate_cell
from eval.schema import EvalItem
from eval.sweep import GateScore, _git_sha, load_scores, rescore, select_threshold
from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.data.doc_models import write_text

REPORT = Path("eval/reports/model_veto.md")
# Full-graph confirmation runs with the veto on: the two lookalike holdout items that
# the gate-level comparison flips, plus every dev model_number item.
CONFIRM = {
    "token": Path("eval/runs/veto-token.jsonl"),
    "faq_unit": Path("eval/runs/veto-faq.jsonl"),
}
VARIANTS = {"before": False, "after": True}


def variant_settings(base: Settings, on: bool) -> Settings:
    settings = base.model_copy(deep=True)
    settings.gate.require_model_number_hit = on
    return settings


def scored(
    base: Settings, on: bool
) -> tuple[dict[str, dict[str, list[GateScore]]], dict[str, float | None], dict[str, EvalItem]]:
    """Per index and set: rescored records, plus each index's dev-selected threshold."""
    results: dict[str, dict[str, list[GateScore]]] = {}
    thresholds: dict[str, float | None] = {}
    items: dict[str, EvalItem] = {}
    for index in INDEXES:
        settings = variant_settings(index_settings(base, index), on)
        results[index.name] = {}
        for name in SETS:
            set_list = set_items(settings, name)
            items.update({item.id: item for item in set_list})
            records = load_scores(cache_path(index, name))[1]
            results[index.name][name] = rescore(
                records, set_list, settings, REPO_ROOT / index.chunks
            )
        thresholds[index.name] = select_threshold(results[index.name]["dev"], "midpoint")
    return results, thresholds, items


def counts(records: list[GateScore], threshold: float | None) -> tuple[str, str]:
    answerable = [r for r in records if r.answerable]
    no_answer = [r for r in records if not r.answerable]
    fr = (
        rate_cell(sum(not passes(r, threshold) for r in answerable), len(answerable))
        if answerable
        else "n/a"
    )
    fa = (
        rate_cell(sum(passes(r, threshold) for r in no_answer), len(no_answer))
        if no_answer
        else "n/a"
    )
    return fr, fa


def index_lines(
    index: str,
    before: dict[str, list[GateScore]],
    after: dict[str, list[GateScore]],
    thresholds: tuple[float | None, float | None],
    items: dict[str, EvalItem],
) -> list[str]:
    lines = [
        f"## Index `{index}`",
        "",
        f"Dev-selected threshold: before {thresholds[0]}, after {thresholds[1]}.",
        "",
        "| Set | Veto | False reject (gate) | False accept (gate) |",
        "|---|---|---:|---:|",
    ]
    flips: list[str] = []
    for name in SETS:
        for label, runs, threshold in (
            ("before", before, thresholds[0]),
            ("after", after, thresholds[1]),
        ):
            fr, fa = counts(runs[name], threshold)
            lines.append(f"| {LABELS[name]} | {label} | {fr} | {fa} |")
        old = {r.id: passes(r, thresholds[0]) for r in before[name]}
        for record in after[name]:
            now = passes(record, thresholds[1])
            if now != old[record.id]:
                item = items[record.id]
                kind = "answerable" if item.answerable else "no-answer"
                change = "now passes" if now else "now blocked"
                flips.append(f"- {name}, {kind}, {change}: {item.question}")
    lines += ["", "Items whose gate decision changed:", ""]
    lines += flips or ["- none"]
    return [*lines, ""]


def confirm_lines() -> list[str]:
    from collections import Counter

    from eval.store_scope_report import load_run

    lines = [
        "## Full-graph confirmation (veto on)",
        "",
        "The full graph retrieves with the rewritten query, so the gate can differ from the",
        "snapshots. Items: the two flipped holdout items and the 30 dev `model_number` items.",
        "",
        "| Index | Kind | Gate reason | Final outcome | Items |",
        "|---|---|---|---|---:|",
    ]
    found = False
    for index, path in CONFIRM.items():
        if not (REPO_ROOT / path).exists():
            continue
        found = True
        counts: Counter[tuple[str, str, str]] = Counter()
        for record in load_run(REPO_ROOT / path)[1].values():
            kind = "answerable" if record.item.answerable else "no-answer"
            reason = str((record.gate or {}).get("reason"))
            counts[(kind, reason, "accepted" if record.accepted else "handed off")] += 1
        for (kind, reason, outcome), count in sorted(counts.items()):
            lines.append(f"| {index} | {kind} | {reason} | {outcome} | {count} |")
    return [*lines, ""] if found else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    base = get_settings()
    before, before_t, items = scored(base, False)
    after, after_t, _ = scored(base, True)
    lines = [
        "# Model-number veto",
        "",
        "Generated by `make eval-model-veto`. Gate only; cached retrieval from",
        "`make eval-chunking-ab` (both indexes with text dedupe); no LLM calls.",
        "Before: the specific-term veto alone. After: plus the model-number veto",
        "(`gate.require_model_number_hit`).",
        "",
        f"- Git SHA: `{_git_sha()}`",
        "",
    ]
    for index in INDEXES:
        lines += index_lines(
            index.name,
            before[index.name],
            after[index.name],
            (before_t[index.name], after_t[index.name]),
            items,
        )
    lines += confirm_lines()
    lines += [
        "## Limits",
        "",
        "Snapshots use the raw question; the full graph retrieves with a rewritten query.",
        "The token-index snapshots used text dedupe, which production does not.",
        "Only the paraphrase holdout is unseen; holdout v1 was read to find this bug.",
        "The confirmation ran once; an answerable item handed off after the gate passed",
        "is a later model step, not the veto.",
    ]
    write_text(REPO_ROOT / REPORT, "\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
