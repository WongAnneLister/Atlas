"""Chunking A/B: token-window index vs one-FAQ-per-chunk index, retrieval and gate only.

Both indexes are queried through the production path (pool, store scope, top k) on
identical questions. No LLM is called, so results are deterministic. Each index gets
its own dev-selected gate threshold (midpoint rule); other sets never tune.
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
from dataclasses import dataclass
from pathlib import Path

from eval.build_holdout import VERSIONS as HOLDOUTS
from eval.build_paraphrase_holdout import OUTPUT as PARAPHRASE
from eval.build_store_controls import OUTPUT as CONTROLS
from eval.common import load_items
from eval.gate_round3 import rate_cell
from eval.schema import EvalItem
from eval.sweep import (
    GateScore,
    _eval_paths,
    _git_sha,
    collect_scores,
    load_local_chunks,
    load_scores,
    rescore,
    select_threshold,
)
from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.data.doc_models import write_text
from support_agent.retrieval.chunking import Chunk

log = logging.getLogger(__name__)
REPORT = Path("eval/reports/chunking.md")
EVIDENCE_CHARS = 60


@dataclass(frozen=True)
class Index:
    name: str
    collection: str
    strategy: str
    chunks: Path


INDEXES = [
    Index("token", "support_chunks", "token", Path("data/processed/chunks_token_v1.jsonl")),
    Index(
        "faq_unit", "support_chunks_faq_v1", "faq_unit", Path("data/processed/chunks_faq_v1.jsonl")
    ),
]
SETS: dict[str, Path | None] = {
    "dev": None,
    "test": None,
    "paraphrase": PARAPHRASE,
    "controls": CONTROLS,
    "holdout_v1": HOLDOUTS["v1"].output,
    "holdout_v2": HOLDOUTS["v2"].output,
}
LABELS = {
    "dev": "Dev (eval_v1, mostly FAQ wording)",
    "test": "Old test (seen)",
    "paraphrase": "Paraphrase holdout (fresh)",
    "controls": "Store controls (seen)",
    "holdout_v1": "Near-miss holdout v1 (seen)",
    "holdout_v2": "Cross-store holdout v2 (seen)",
}


def index_settings(base: Settings, index: Index) -> Settings:
    settings = base.model_copy(deep=True)
    settings.milvus.collection = index.collection
    settings.chunk.strategy = index.strategy  # type: ignore[assignment]
    settings.chunk.product_window_header = True
    settings.retrieval.dedupe_text = True
    return settings


def cache_path(index: Index, name: str) -> Path:
    return REPO_ROOT / f"eval/runs/chunk-ab-{index.name}-{name}.jsonl"


def set_items(settings: Settings, name: str) -> list[EvalItem]:
    path = SETS[name]
    if path is None:
        return _eval_paths(settings, name)[1]
    return load_items(REPO_ROOT / path)


def collect(settings: Settings, index: Index, name: str) -> list[GateScore]:
    path = SETS[name]
    if path is None:
        return collect_scores(settings, name, cache_path(index, name))
    items = load_items(REPO_ROOT / path)
    corpus = _eval_paths(settings, "dev")[2]
    return collect_scores(
        settings, name, cache_path(index, name), (REPO_ROOT / path, items, corpus)
    )


def evidence_strings(item: EvalItem) -> list[str]:
    try:
        notes = json.loads(item.notes)
    except ValueError:
        notes = {}
    if isinstance(notes, dict) and notes.get("evidence"):
        return [str(notes["evidence"])]
    return [point[:EVIDENCE_CHARS] for point in item.answer_points]


def _norm(text: str) -> str:
    return " ".join(text.split())


def evidence_hit(item: EvalItem, record: GateScore, texts: dict[str, Chunk]) -> bool:
    joined = " ".join(_norm(texts[c.chunk_id].text) for c in record.chunks if c.chunk_id in texts)
    return all(_norm(e) in joined for e in evidence_strings(item))


def passes(record: GateScore, threshold: float | None) -> bool:
    return threshold is not None and not record.vetoed and record.score >= threshold


def summary_rows(
    name: str,
    results: dict[str, list[GateScore]],
    thresholds: dict[str, float | None],
    items: dict[str, EvalItem],
    texts: dict[str, dict[str, Chunk]],
) -> list[str]:
    lines = [
        f"### {LABELS[name]}",
        "",
        "| Index | Answerable | Section Recall@5 | Gold at 1 | Evidence hit@5 | "
        "Median top rerank | Gate pass (answerable) | Gate pass (no-answer) | "
        "Median top-5 tokens |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for index_name, records in results.items():
        t = thresholds[index_name]
        ans = [r for r in records if r.answerable]
        no = [r for r in records if not r.answerable]
        index_texts = texts[index_name]
        recall = [
            len(set(items[r.id].gold_sections) & set(r.ranked_section_ids))
            / len(items[r.id].gold_sections)
            for r in ans
        ]
        gold1 = [
            bool(r.ranked_section_ids) and r.ranked_section_ids[0] in items[r.id].gold_sections
            for r in ans
        ]
        hits = [evidence_hit(items[r.id], r, index_texts) for r in ans]
        tops = [r.signals.get("top_score", 0.0) for r in ans]
        tokens = [
            sum(index_texts[c.chunk_id].n_tokens for c in r.chunks if c.chunk_id in index_texts)
            for r in records
        ]
        mean = statistics.mean
        lines.append(
            f"| {index_name} | {len(ans)} | "
            + (
                f"{mean(recall):.3f} | {mean(gold1):.3f} | {sum(hits)}/{len(ans)} | "
                f"{statistics.median(tops):.3f} | "
                f"{rate_cell(sum(passes(r, t) for r in ans), len(ans))} | "
                if ans
                else "n/a | n/a | n/a | n/a | n/a | "
            )
            + (rate_cell(sum(passes(r, t) for r in no), len(no)) if no else "n/a")
            + f" | {statistics.median(tokens):.0f} |"
        )
    return [*lines, ""]


def family_rows(
    name: str,
    results: dict[str, list[GateScore]],
    items: dict[str, EvalItem],
    texts: dict[str, dict[str, Chunk]],
) -> list[str]:
    families: dict[str, list[str]] = {}
    for record in next(iter(results.values())):
        item = items[record.id]
        if not item.answerable:
            continue
        try:
            family = json.loads(item.notes).get("family", item.group)
        except ValueError:
            family = item.group
        families.setdefault(family, []).append(record.id)
    if len(families) < 2:
        return []
    header = (
        "| Family | Items | "
        + " | ".join(f"{n} evidence hit / median top rerank" for n in results)
        + " |"
    )
    lines = [header, "|---|---:|" + "---:|" * len(results)]
    for family, ids in sorted(families.items()):
        cells = []
        for index_name, records in results.items():
            by_id = {r.id: r for r in records}
            hit = sum(evidence_hit(items[i], by_id[i], texts[index_name]) for i in ids)
            top = statistics.median(by_id[i].signals.get("top_score", 0.0) for i in ids)
            cells.append(f"{hit}/{len(ids)} / {top:.3f}")
        lines.append(f"| {family} | {len(ids)} | " + " | ".join(cells) + " |")
    return [*lines, ""]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-collect", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    base = get_settings()
    results: dict[str, dict[str, list[GateScore]]] = {name: {} for name in SETS}
    thresholds: dict[str, float | None] = {}
    texts: dict[str, dict[str, Chunk]] = {}
    items: dict[str, EvalItem] = {}
    for index in INDEXES:
        settings = index_settings(base, index)
        texts[index.name] = load_local_chunks(settings, REPO_ROOT / index.chunks)
        for name in SETS:
            set_list = set_items(settings, name)
            items.update({item.id: item for item in set_list})
            if args.no_collect:
                records = load_scores(cache_path(index, name))[1]
            else:
                records = collect(settings, index, name)
            results[name][index.name] = rescore(
                records, list(items.values()), settings, REPO_ROOT / index.chunks
            )
        thresholds[index.name] = select_threshold(results["dev"][index.name], "midpoint")
    lines = [
        "# Chunking A/B",
        "",
        "Generated by `make eval-chunking-ab`. Retrieval and gate only; no LLM calls.",
        "Both indexes use the production path: pool, store scope, text dedupe, top 5.",
        "",
        f"- Git SHA: `{_git_sha()}`",
        *[
            f"- `{i.name}`: collection `{i.collection}`, strategy `{i.strategy}`, "
            f"{len(texts[i.name])} chunks, dev-selected threshold "
            f"{thresholds[i.name]:.2f}"
            if thresholds[i.name] is not None
            else f"- `{i.name}`: no threshold"
            for i in INDEXES
        ],
        "",
        "Evidence hit@5: every evidence string of the item (start of each gold answer, or",
        "the manual anchor) appears in one of the five chunks the gate and model receive.",
        "",
    ]
    for name in SETS:
        lines += summary_rows(name, results[name], thresholds, items, texts)
        lines += family_rows(name, results[name], items, texts)
    lines += [
        "## Limits",
        "",
        "Section recall is coarse for manuals (one section per product); use evidence hit.",
        "Text dedupe keeps one copy of a FAQ filed under two sections. When both sections",
        "are gold, section recall drops although the evidence is still there.",
        "Evidence strings are exact text matches; a chunk can answer without containing them.",
        "Only the paraphrase holdout is unseen; the gate threshold is re-selected on dev.",
    ]
    write_text(REPO_ROOT / REPORT, "\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
