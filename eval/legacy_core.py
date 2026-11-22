"""Replay intent and retrieval reports from measured run records."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from eval.core_run_reporting import manifest_for_core, write_intervals
from eval.intent_records import IntentRecord, IntentRun
from eval.intent_report import write_report
from eval.intent_run_metrics import confusion_observation
from eval.metrics import hit_all_at_k, mrr, recall_at_k
from eval.registry import load_registry
from eval.retrieval_records import RetrievalReportRun, RetrievalRun, SearchRecord
from eval.retrieval_report import write_reports
from eval.run_record import (
    DatasetVersion,
    RunItem,
    RunManifest,
    read_run,
    summarize_metrics,
    write_run,
)
from support_agent.config import REPO_ROOT
from support_agent.graph.intents import INTENT_TO_PATH, Intent

RUNS = REPO_ROOT / "eval/runs"


def dataset_version(name: str, sha256: str) -> DatasetVersion:
    entry = load_registry().get(name)
    return DatasetVersion(
        version=entry.version if entry and entry.sha256 == sha256 else None, sha256=sha256
    )


def _safe_intent_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Keep report provenance while removing URL credentials and private query parameters."""
    safe = dict(metadata)
    options = safe.get("model_options", {})
    safe["model_options"] = {name: options[name] for name in ("temperature",) if name in options}
    if thinking := options.get("extra_body", {}).get("thinking"):
        safe["model_options"]["extra_body"] = {"thinking": {"type": thinking.get("type")}}
    if safe.get("endpoint"):
        parts = urlsplit(str(safe["endpoint"]))
        safe["endpoint"] = urlunsplit(
            (parts.scheme, parts.netloc.rsplit("@", 1)[-1], parts.path, "", "")
        )
    return safe


def intent_items(records: list[IntentRecord]) -> list[RunItem]:
    items = []
    for record in records:
        gold, predicted = record.item.intent, record.predicted
        correct = gold == predicted
        items.append(
            RunItem(
                id=record.item.id,
                group=gold.value,
                metrics={
                    "accuracy": correct,
                    "path_accuracy": INTENT_TO_PATH[gold] == INTENT_TO_PATH[predicted],
                    "parse_failure_rate": record.parse_failed,
                    "mean_latency_s": record.latency_s,
                    "macro_precision": confusion_observation(gold, predicted),
                    "macro_recall": confusion_observation(gold, predicted),
                    f"{gold.value}.recall": correct,
                    f"{predicted.value}.precision": correct,
                },
                payload=record.model_dump(mode="json"),
            )
        )
    return items


def save_intent(
    run: IntentRun,
    command: list[str],
    *,
    root: Path = RUNS,
    suffix: str | None = None,
    dirty: bool | None = None,
) -> Path:
    meta = _safe_intent_metadata(run.metadata)
    datasets = {"intent_holdout": dataset_version("intent_holdout", meta["dataset_hash"])}
    # This is the dev product source used when constructing the intent holdout.
    if eval_hash := meta.get("input_hashes", {}).get("retrieval_eval_hash"):
        datasets["eval_v1"] = dataset_version("eval_v1", eval_hash)
    models = {"fast": meta["model"]}
    models.update(
        {f"fast_response_{i}": model for i, model in enumerate(meta.get("response_models", []), 1)}
    )
    manifest = manifest_for_core("intent", "intent_holdout", meta, datasets, models, command, dirty)
    rows = intent_items(run.records)
    return write_run(
        manifest,
        rows,
        root=root,
        suffix=suffix,
        metrics=summarize_metrics(
            rows, statistics={"macro_precision": "macro_precision", "macro_recall": "macro_recall"}
        ),
    )


def import_intent(path: Path, *, root: Path = RUNS, suffix: str | None = None) -> Path:
    return save_intent(
        IntentRun.model_validate_json(path.read_text(encoding="utf-8")),
        ["eval-import-legacy", "intent", path.name],
        root=root,
        suffix=suffix,
    )


def render_intent(run_path: Path, report_path: Path) -> None:
    run = read_run(run_path)
    if run.manifest.kind != "intent":
        raise ValueError("Expected an intent run")
    records = [IntentRecord.model_validate(item.payload) for item in run.items]
    write_report(IntentRun(metadata=run.manifest.source["metadata"], records=records), report_path)
    names = [
        "accuracy",
        "path_accuracy",
        "macro_precision",
        "macro_recall",
        "parse_failure_rate",
        "mean_latency_s",
        *(f"{intent.value}.{metric}" for intent in Intent for metric in ("precision", "recall")),
    ]
    write_intervals(report_path, run, names)


def _retrieval_item(
    *,
    item_id: str,
    split: str,
    mode: str,
    group: str,
    metrics: dict[str, float | bool],
    payload: dict[str, Any],
) -> RunItem:
    metrics = {
        f"{split}.{mode}.{scope}.{name}": value
        for scope in ("overall", group)
        for name, value in metrics.items()
    }
    return RunItem(
        id=f"{split}/{mode}/{item_id}",
        group=group,
        answerable=True,
        metrics=metrics,
        payload=payload,
    )


def retrieval_items(records: list[SearchRecord], ks: list[int]) -> list[RunItem]:
    items = []
    cutoff = max(ks)
    for record in records:
        item = record.item
        sections = [chunk.section_id for chunk in record.chunks[:cutoff]]
        metrics = {f"recall@{k}": recall_at_k(sections, item.gold_sections, k) for k in ks}
        metrics.update({f"mrr@{cutoff}": mrr(sections, item.gold_sections)})
        metrics["mean_latency_s"] = record.latency_s
        if item.group == "cross_doc":
            metrics[f"cross_doc_hit_all@{cutoff}"] = hit_all_at_k(
                sections, item.gold_sections, cutoff
            )
        items.append(
            _retrieval_item(
                item_id=item.id,
                split=item.split,
                mode=record.mode,
                group=item.group,
                metrics=metrics,
                payload={
                    "item": item.model_dump(
                        include={"id", "split", "group", "gold_sections", "answerable"}
                    ),
                    "mode": record.mode,
                    "chunks": [
                        {"section_id": chunk.section_id, "chunk_id": chunk.chunk_id}
                        for chunk in record.chunks
                    ],
                    "latency_s": record.latency_s,
                    "cache_hit": record.cache_hit,
                    "filters": record.filters.model_dump(mode="json") if record.filters else None,
                    "filters_applied": record.filters_applied,
                },
            )
        )
    return items


def _retrieval_manifest(
    split: str,
    meta: dict[str, Any],
    command: list[str],
    dirty: bool | None = None,
) -> RunManifest:
    datasets = {"eval_v1": dataset_version("eval_v1", meta["eval_file_hash"])}
    return manifest_for_core("retrieval", split, meta, datasets, meta["models"], command, dirty)


def save_retrieval(
    run: RetrievalRun,
    command: list[str],
    *,
    root: Path = RUNS,
    suffix: str | None = None,
    dirty: bool | None = None,
) -> Path:
    meta = run.metadata.model_dump(mode="json")
    # The renderer needs execution/experiment metadata, not the whole runtime configuration.
    meta["settings"] = {
        section: {
            name: meta["settings"][section][name]
            for name in names
            if name in meta["settings"][section]
        }
        for section, names in {
            "retrieval": (
                "embedding_device",
                "reranker_device",
                "reranker_batch_size",
                "reranker_max_tokens",
            ),
            "retrieval_eval": (
                "metric_ks",
                "baseline_collection",
                "heading_ablation_collection",
                "local_chunk_text",
                "target_recall_at_5",
            ),
        }.items()
    }
    manifest = _retrieval_manifest(run.requested_split, meta, command, dirty)
    return write_run(
        manifest,
        retrieval_items(run.records, run.metadata.settings["retrieval_eval"]["metric_ks"]),
        root=root,
        suffix=suffix,
    )


def import_retrieval(path: Path, *, root: Path = RUNS, suffix: str | None = None) -> Path:
    return save_retrieval(
        RetrievalRun.model_validate_json(path.read_text(encoding="utf-8")),
        ["eval-import-legacy", "retrieval", path.name],
        root=root,
        suffix=suffix,
    )


def render_retrieval(run_path: Path, folder: Path, guide_path: Path) -> None:
    import_run = read_run(run_path)
    manifest = import_run.manifest
    if manifest.kind != "retrieval" or manifest.source.get("csv_only"):
        raise ValueError("The full retrieval run is required to render rank diagnostics")
    report_run = RetrievalReportRun.model_validate(
        {
            "metadata": manifest.source["metadata"],
            "requested_split": manifest.split,
            "records": [item.payload for item in import_run.items],
        }
    )
    write_reports(report_run, folder, guide_path)
    write_intervals(
        folder / "retrieval.md",
        import_run,
        [name for name in import_run.metrics.metrics if ".overall." in name],
    )
