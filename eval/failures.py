"""Inspect local questions and retrieved headings for incomplete evidence coverage."""

from __future__ import annotations

import argparse

from eval.metrics import recall_at_k
from eval.retrieval_records import RetrievalRun
from support_agent.config import REPO_ROOT, get_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", default="hybrid_rerank")
    parser.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    args = parser.parse_args(argv)
    settings = get_settings()
    run = RetrievalRun.model_validate_json(
        (REPO_ROOT / settings.retrieval_eval.cache_dir / "latest_run.json").read_text()
    )
    selected = [
        r
        for r in run.records
        if r.mode == args.mode and (args.split == "all" or r.item.split == args.split)
    ]
    if not selected:
        parser.error("No records for the requested mode/split; run make eval-retrieval first")
    cutoff = max(run.metadata.settings["retrieval_eval"]["metric_ks"])
    for record in selected:
        sections = [chunk.section_id for chunk in record.chunks]
        if recall_at_k(sections, record.item.gold_sections, cutoff) == 1:
            continue
        print(f"{record.item.id} [{record.item.group}/{record.item.split}] {record.item.question}")
        print("  gold: " + ", ".join(record.item.gold_sections))
        for rank, chunk in enumerate(record.chunks[:cutoff], 1):
            print(f"  {rank}: {chunk.section_id} | {chunk.heading_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
