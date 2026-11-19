"""Import saved rank exports for paired comparison without the full retrieval cache."""

from __future__ import annotations

import csv
import json
import re
from hashlib import sha256
from pathlib import Path

from eval.legacy_core import RUNS, _retrieval_item, _retrieval_manifest
from eval.metrics import hit_all_at_k, mrr, recall_at_k
from eval.run_record import RunItem, write_run


def retrieval_csv_items(paths: list[Path]) -> list[RunItem]:
    items = []
    for path in paths:
        with path.open(encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source)
            cutoffs = sorted(
                int(name.split("@")[1])
                for name in reader.fieldnames or []
                if re.fullmatch(r"recall@\d+", name)
            )
            if not cutoffs or any(k < 1 for k in cutoffs):
                raise ValueError(f"Missing valid recall columns in {path}")
            cutoff = max(cutoffs)
            for row in reader:
                gold = json.loads(row["gold_sections"])
                ranked = json.loads(row["ranked_section_ids"])
                hit = hit_all_at_k(ranked, gold, cutoff)
                if row[f"hit_all@{cutoff}"] != str(hit):
                    raise ValueError(f"Hit-all disagrees with ranks for {row['id']}")
                values = {f"recall@{k}": recall_at_k(ranked, gold, k) for k in cutoffs}
                values[f"mrr@{cutoff}"] = mrr(ranked[:cutoff], gold)
                if any(float(row[name]) != value for name, value in values.items()):
                    raise ValueError(f"Recall or MRR disagrees with ranks for {row['id']}")
                metrics: dict[str, float | bool] = dict(values)
                metrics["mean_latency_s"] = float(row["latency_s"])
                if row["group"] == "cross_doc":
                    metrics[f"cross_doc_hit_all@{cutoff}"] = hit
                items.append(
                    _retrieval_item(
                        item_id=row["id"],
                        split=row["split"],
                        mode=row["mode"],
                        group=row["group"],
                        metrics=metrics,
                        payload=row,
                    )
                )
    if not items:
        raise ValueError("No retrieval CSV rows to import")
    return items


def import_retrieval_csv(
    paths: list[Path],
    report: Path,
    *,
    root: Path = RUNS,
    suffix: str | None = None,
) -> Path:
    values = dict(
        tuple(line[2:].split(": ", 1))
        for line in report.read_text(encoding="utf-8").splitlines()
        if line.startswith("- ") and ": " in line
    )
    meta = {
        "git_sha": values["Git SHA (base revision)"].strip("`"),
        "config_hash": values["Config hash"].strip("`"),
        "eval_file_hash": values["Eval file hash"].strip("`"),
        "corpus_hash": values["Corpus hash"].strip("`"),
        "date": values["Date (UTC)"],
        "models": json.loads(values["Models"]),
        "dataset_versions": json.loads(values["Dataset versions"]),
    }
    manifest = _retrieval_manifest(
        values["Requested split"].split(";", 1)[0],
        meta,
        ["eval-import-legacy", "retrieval-csv", *(path.name for path in paths), report.name],
    )
    manifest.source.update(
        csv_only=True,
        csv_hashes={path.name: sha256(path.read_bytes()).hexdigest() for path in paths},
    )
    return write_run(manifest, retrieval_csv_items(paths), root=root, suffix=suffix)
