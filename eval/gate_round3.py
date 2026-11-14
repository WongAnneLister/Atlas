"""Gate round three: compare gate variants offline on identical retrieval snapshots.

Every variant reuses the same cached reranked chunks, so only gate logic differs.
Each variant picks its threshold on dev with its own rule; test and holdout never tune.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eval.build_holdout import OUTPUT as HOLDOUT_PATH
from eval.build_holdout import family_of, is_closed_list
from eval.common import load_items, set_hash
from eval.e2e_records import E2ERecord
from eval.schema import EvalItem
from eval.sweep import (
    GateScore,
    _eval_paths,
    _git_sha,
    collect_scores,
    load_scores,
    rescore,
    score_config_hash,
    select_threshold,
)
from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.data.doc_models import digest, json_text, write_text

log = logging.getLogger(__name__)
REPORT = Path("eval/reports/gate_round3.md")
WILSON_Z = 1.959964  # two-sided 95% normal quantile


@dataclass(frozen=True)
class Variant:
    name: str
    description: str
    gate: dict[str, Any]


VARIANTS = [
    Variant(
        "V0 round two",
        "neutral key_hit, no entity terms, no veto, lowest safe threshold",
        {
            "key_hit_without_terms": "neutral",
            "entity_terms": False,
            "require_specific_term_hit": False,
            "threshold_rule": "lowest",
        },
    ),
    Variant(
        "V1 exclude + midpoint",
        "key_hit excluded without terms; midpoint threshold",
        {
            "key_hit_without_terms": "exclude",
            "entity_terms": False,
            "require_specific_term_hit": False,
            "threshold_rule": "midpoint",
        },
    ),
    Variant(
        "V2 + entity terms",
        "V1 plus capitalised names as key terms",
        {
            "key_hit_without_terms": "exclude",
            "entity_terms": True,
            "require_specific_term_hit": False,
            "threshold_rule": "midpoint",
        },
    ),
    Variant(
        "V3 + veto (shipped)",
        "V2 plus a veto when no named model or entity appears in the top chunks",
        {
            "key_hit_without_terms": "exclude",
            "entity_terms": True,
            "require_specific_term_hit": True,
            "threshold_rule": "midpoint",
        },
    ),
]


def wilson(successes: int, total: int) -> tuple[float, float]:
    """Two-sided 95% Wilson score interval for a binomial proportion."""
    if total <= 0:
        raise ValueError("Wilson interval needs a positive total")
    p = successes / total
    z2 = WILSON_Z**2
    centre = (p + z2 / (2 * total)) / (1 + z2 / total)
    half = WILSON_Z * math.sqrt(p * (1 - p) / total + z2 / (4 * total**2)) / (1 + z2 / total)
    return max(0.0, centre - half), min(1.0, centre + half)


def rate_cell(successes: int, total: int) -> str:
    low, high = wilson(successes, total)
    return f"{successes}/{total} ({successes / total:.2%}; 95% CI {low:.1%}-{high:.1%})"


def variant_settings(settings: Settings, variant: Variant) -> Settings:
    updated = settings.model_copy(deep=True)
    updated.gate = updated.gate.model_copy(update=variant.gate)
    return updated


def passes(record: GateScore, threshold: float | None) -> bool:
    return threshold is not None and not record.vetoed and record.score >= threshold


@dataclass
class VariantResult:
    variant: Variant
    threshold: float | None
    dev: list[GateScore]
    test: list[GateScore]
    holdout: list[GateScore]


def evaluate_variant(
    settings: Settings,
    variant: Variant,
    snapshots: dict[str, list[GateScore]],
    items: list[EvalItem],
) -> VariantResult:
    local = variant_settings(settings, variant)
    dev = rescore(snapshots["dev"], items, local)
    threshold = select_threshold(dev, local.gate.threshold_rule)
    return VariantResult(
        variant,
        threshold,
        dev,
        rescore(snapshots["test"], items, local),
        rescore(snapshots["holdout"], items, local),
    )


def count_false_accepts(records: list[GateScore], threshold: float | None) -> int:
    return sum(passes(r, threshold) for r in records if not r.answerable)


def count_false_rejects(records: list[GateScore], threshold: float | None) -> int:
    return sum(not passes(r, threshold) for r in records if r.answerable)


def _summary_rows(results: list[VariantResult]) -> list[str]:
    rows = [
        "| Variant | Dev threshold | Dev FA | Dev FR | Test FA | Test FR | Holdout FA |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        t = result.threshold
        cells = []
        for records in (result.dev, result.test):
            no_answer = sum(not r.answerable for r in records)
            answerable = sum(r.answerable for r in records)
            cells.append(f"{count_false_accepts(records, t)}/{no_answer}")
            cells.append(f"{count_false_rejects(records, t)}/{answerable}")
        holdout = rate_cell(count_false_accepts(result.holdout, t), len(result.holdout))
        threshold = f"{t:.2f}" if t is not None else "none"
        rows.append(f"| {result.variant.name} | {threshold} | {' | '.join(cells)} | {holdout} |")
    return rows


def _family_rows(results: list[VariantResult], items: dict[str, EvalItem]) -> list[str]:
    families = sorted({family_of(items[r.id]) for r in results[0].holdout})
    header = "| Family | Items | " + " | ".join(r.variant.name for r in results) + " |"
    rows = [header, "|---|---:|" + "---:|" * len(results)]
    groups: list[tuple[str, Any]] = [(f, lambda i, f=f: family_of(i) == f) for f in families]
    groups += [
        ("closed-list items", is_closed_list),
        ("all other items", lambda i: not is_closed_list(i)),
    ]
    for label, keep in groups:
        ids = {r.id for r in results[0].holdout if keep(items[r.id])}
        cells = [
            str(count_false_accepts([r for r in result.holdout if r.id in ids], result.threshold))
            for result in results
        ]
        rows.append(f"| {label} | {len(ids)} | " + " | ".join(cells) + " |")
    return rows


def _dev_gap_rows(results: list[VariantResult]) -> list[str]:
    rows = [
        "| Variant | Max dev no-answer | Min dev answerable | Vetoed dev items |",
        "|---|---:|---:|---:|",
    ]
    for result in results:
        no_answer = [r.score for r in result.dev if not r.answerable and not r.vetoed]
        answerable = [r.score for r in result.dev if r.answerable and not r.vetoed]
        rows.append(
            f"| {result.variant.name} | {max(no_answer, default=0.0):.4f} | "
            f"{min(answerable, default=0.0):.4f} | {sum(r.vetoed for r in result.dev)} |"
        )
    return rows


def _changed_test_rows(results: list[VariantResult], items: dict[str, EvalItem]) -> list[str]:
    base, shipped = results[0], results[-1]
    shipped_by_id = {r.id: r for r in shipped.test}
    rows = ["| Item | Group | V0 passes | V3 passes | V3 reason |", "|---|---|---:|---:|---|"]
    for record in base.test:
        after = shipped_by_id[record.id]
        before_pass, after_pass = passes(record, base.threshold), passes(after, shipped.threshold)
        if before_pass != after_pass:
            reason = "vetoed" if after.vetoed else "below threshold" if not after_pass else "-"
            rows.append(
                f"| {record.id} | {items[record.id].group} | {before_pass} | {after_pass} | "
                f"{reason} |"
            )
    return rows if len(rows) > 2 else [*rows, "| none | | | | |"]


def _e2e_rows(path: Path, items: dict[str, EvalItem]) -> list[str]:
    records = [
        E2ERecord.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()[1:]
        if line.strip()
    ]
    accepted = [r for r in records if r.accepted]
    closed = [r for r in accepted if is_closed_list(items[r.item.id])]
    reasons: dict[str, int] = {}
    for record in records:
        key = record.handoff_reason or ("accepted" if record.accepted else "no handoff")
        reasons[key] = reasons.get(key, 0) + 1
    lines = [
        f"- Run file: `{path.relative_to(REPO_ROOT).as_posix()}` ({len(records)} items)",
        f"- Full-graph false accepts: {rate_cell(len(accepted), len(records))}",
        f"- Of those, closed-list items: {len(closed)}",
        "- Outcomes: " + ", ".join(f"{k} {v}" for k, v in sorted(reasons.items())),
    ]
    families: dict[str, int] = {}
    for record in accepted:
        key = f"{family_of(items[record.item.id])} / path {record.path}"
        families[key] = families.get(key, 0) + 1
    lines.append(
        "- Accepted by family and path: "
        + ", ".join(f"{key} {count}" for key, count in sorted(families.items()))
    )
    lines.append(
        "- Gate passed: "
        + str(sum(bool(r.gate and r.gate.get("passed")) for r in records))
        + f"/{len(records)}"
    )
    lines.extend(
        f"  - accepted: `{r.item.id}` ({family_of(items[r.item.id])}, path {r.path})"
        for r in accepted
    )
    return lines


def write_report(
    results: list[VariantResult],
    items: list[EvalItem],
    holdout: list[EvalItem],
    provenance: dict[str, str],
    e2e_runs: dict[str, Path],
    path: Path,
) -> None:
    by_id = {item.id: item for item in [*items, *holdout]}
    lines = [
        "# Gate round three",
        "",
        "Generated by `make eval-gate-round3`. All variants share one retrieval snapshot per",
        "question, so only gate logic differs. Each variant selects its threshold on dev.",
        "The old test split is regression evidence (already seen); the near-miss holdout",
        "was frozen in an earlier commit and never tunes anything.",
        "",
        *[f"- {key}: `{value}`" for key, value in provenance.items()],
        "",
        "## Variants",
        "",
        *[f"- **{r.variant.name}**: {r.variant.description}." for r in results],
        "",
        "## Gate-level results",
        "",
        "FA = no-answer items that pass the gate. FR = answerable items the gate rejects.",
        "Gate-level rates exclude the answer-stage coverage check.",
        "",
        *_summary_rows(results),
        "",
        "## Dev separation",
        "",
        *_dev_gap_rows(results),
        "",
        "## Holdout false accepts by family",
        "",
        *_family_rows(results, by_id),
        "",
        "## Old test items whose gate outcome changed (V0 to V3)",
        "",
        *_changed_test_rows(results, by_id),
    ]
    for label, run in e2e_runs.items():
        lines.extend(["", f"## Full graph on the holdout: {label}", ""])
        lines.extend(
            _e2e_rows(run, by_id)
            if run.exists()
            else [f"Not measured: no run file at `{run.relative_to(REPO_ROOT).as_posix()}`."]
        )
    lines.extend(
        [
            "",
            "## Limits",
            "",
            "The holdout is agent-authored and unreviewed; it has no answerable items.",
            "Dev no-answer questions are templated and far from the corpus.",
            "The veto idea was motivated by a known test failure (Cash App Pay).",
            "That is why the fresh holdout, not the old test, judges it.",
            "A zero count is not a production guarantee; read the interval.",
            "Full-graph run files record model names, not the API endpoint used.",
            "Path A accepts can be tool-path replies that decline without a handoff.",
        ]
    )
    write_text(path, "\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev-cache", type=Path, default=Path("eval/runs/gate_scores_dev.jsonl"))
    parser.add_argument("--test-cache", type=Path, default=Path("eval/runs/gate_scores_test.jsonl"))
    parser.add_argument(
        "--holdout-cache", type=Path, default=Path("eval/runs/gate_scores_holdout.jsonl")
    )
    parser.add_argument(
        "--e2e-before", type=Path, default=Path("eval/runs/round3-holdout-before.jsonl")
    )
    parser.add_argument(
        "--e2e-after", type=Path, default=Path("eval/runs/round3-holdout-after.jsonl")
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = get_settings()
    eval_path, _, corpus_hash = _eval_paths(settings, "dev")
    items = load_items(eval_path)
    holdout_path = REPO_ROOT / HOLDOUT_PATH
    holdout = load_items(holdout_path)
    snapshots: dict[str, list[GateScore]] = {}
    for split, cache in (("dev", args.dev_cache), ("test", args.test_cache)):
        metadata, records = load_scores(REPO_ROOT / cache)
        if metadata.config_hash != score_config_hash(settings):
            raise ValueError(f"{cache} was collected with other retrieval settings; run make sweep")
        snapshots[split] = records
    holdout_cache = REPO_ROOT / args.holdout_cache
    snapshots["holdout"] = collect_scores(
        settings, "holdout", holdout_cache, (holdout_path, holdout, corpus_hash)
    )
    every_item = [*items, *holdout]
    results = [evaluate_variant(settings, v, snapshots, every_item) for v in VARIANTS]
    provenance = {
        "Git SHA": _git_sha(),
        "Retrieval config hash": score_config_hash(settings),
        "Gate config hash": digest(json_text(settings.gate.model_dump(mode="json"))),
        "Eval set hash": set_hash(items),
        "Holdout set hash": set_hash(holdout),
        "Corpus hash": corpus_hash,
        "Models": json.dumps(
            {
                "embedding": settings.retrieval.embedding_model,
                "reranker": settings.retrieval.reranker_model,
            }
        ),
    }
    e2e_runs = {
        "round-two code (before)": REPO_ROOT / args.e2e_before,
        "round-three code (after)": REPO_ROOT / args.e2e_after,
    }
    write_report(results, items, holdout, provenance, e2e_runs, REPO_ROOT / REPORT)
    for result in results:
        log.info(
            "%s: threshold %s, test FA %d, holdout FA %d",
            result.variant.name,
            result.threshold,
            count_false_accepts(result.test, result.threshold),
            count_false_accepts(result.holdout, result.threshold),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
