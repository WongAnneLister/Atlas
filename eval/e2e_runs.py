"""Project E2E rows into shared metrics and replay legacy or standard records."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from eval.e2e_records import E2EMetadata, E2ERecord
from eval.metrics import (
    graph_mrr_at_5,
    graph_recall_at_5,
    noanswer_false_accept,
    part_metric_values,
)
from eval.run_record import (
    RUNS,
    Run,
    RunItem,
    RunManifest,
    dataset_version,
    read_run,
    summarize_metrics,
    write_run,
)
from eval.schema import EvalItem
from support_agent.config import get_settings

STATISTICS: dict[str, Literal["mean", "p95", "p50"]] = {
    "latency_p50": "p50",
    "latency_p95": "p95",
    "first_token_p50": "p50",
    "first_token_p95": "p95",
}


HANDOFF_METRIC_PREFIX = "handoff_reason."
RELIABILITY_METRICS = ("retries", "fallbacks", "repairs")


def project(records: list[E2ERecord], *, chaos: bool = False) -> list[RunItem]:
    rows = []
    reasons = (
        {record.handoff_reason for record in records if record.handoff_reason} if chaos else set()
    )
    for record in records:
        item = record.item
        metrics = {
            "pass_rate": record.accepted,
            "latency_p50": record.latency_full_answer_s,
            "latency_p95": record.latency_full_answer_s,
        }
        if record.latency_first_token_s is not None:
            metrics.update(
                first_token_p50=record.latency_first_token_s,
                first_token_p95=record.latency_first_token_s,
            )
        answerable = (
            item.answerable
            if isinstance(item, EvalItem)
            else all(part.answerable for part in item.parts)
        )
        if isinstance(item, EvalItem) and item.answerable:
            cited = {source["section_id"] for source in record.cited_sources}
            metrics.update(
                false_reject=not record.accepted,
                graph_recall_at_5=graph_recall_at_5(record),
                citation_validity=len(cited & set(item.gold_sections)) / len(cited)
                if cited
                else 0.0,
                graph_mrr_at_5=graph_mrr_at_5(record),
            )
        elif isinstance(item, EvalItem):
            metrics["false_accept"] = noanswer_false_accept(record)
        metrics.update(part_metric_values(record))
        if record.estimated_cost_usd is not None:
            metrics["cost_usd"] = record.estimated_cost_usd
        if chaos:
            events = record.reliability_events
            metrics.update(
                retries=float(sum(event.retries for event in events)),
                fallbacks=float(sum(event.fell_back for event in events)),
                repairs=float(sum(event.repaired for event in events)),
            )
            metrics.update(
                {
                    f"{HANDOFF_METRIC_PREFIX}{reason}": record.handoff_reason == reason
                    for reason in reasons
                }
            )
        rows.append(
            RunItem(
                id=item.id,
                group=item.group,
                answerable=answerable,
                handoff_reason=record.handoff_reason,
                metrics=metrics,
                payload=record.model_dump(mode="json"),
            )
        )
    return rows


def prepare_e2e(
    metadata: E2EMetadata,
    records: list[E2ERecord],
    *,
    dirty: bool | None = None,
    command: list[str] | None = None,
    cost_note: str = "price not set",
) -> Run:
    settings = get_settings()
    amounts = [record.estimated_cost_usd for record in records]
    cost = (
        sum(amount for amount in amounts if amount is not None)
        if (amounts and all(amount is not None for amount in amounts))
        else None
    )
    chaos = metadata.chaos is not None and metadata.chaos.enabled
    items = project(records, chaos=chaos)
    datasets = dataset_version(metadata.eval_file_hash)
    kind = "e2e"
    if chaos:
        kind = "chaos"
    elif "smoke" in datasets:
        kind = "smoke"
    elif "multipart_v1" in datasets:
        kind = "multipart"
    manifest = RunManifest(
        kind=kind,
        split=metadata.split,
        git_sha=metadata.git_sha,
        config_hash=metadata.config_hash,
        models=metadata.models,
        datasets=datasets,
        seed=settings.eval.stats.seed,
        dirty=dirty,
        started_at=datetime.fromisoformat(metadata.date),
        ended_at=datetime.now(UTC) if dirty is not None else None,
        cost_usd=cost,
        cost_note=cost_note if cost is None else None,
        command=command or [],
        source=metadata.model_dump(mode="json"),
    )
    return Run(manifest=manifest, items=items, metrics=summarize_metrics(items, STATISTICS))


def unpack(run: Run) -> tuple[E2EMetadata, list[E2ERecord]]:
    if run.manifest.kind not in {"e2e", "smoke", "multipart"}:
        raise ValueError("Expected an E2E run")
    return E2EMetadata.model_validate(run.manifest.source), [
        E2ERecord.model_validate(row.payload) for row in run.items
    ]


def load_e2e(path: Path) -> tuple[E2EMetadata, list[E2ERecord]]:
    if path.is_dir():
        return unpack(read_run(path))
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"Empty run file: {path}")
    return E2EMetadata.model_validate_json(lines[0]), [
        E2ERecord.model_validate_json(line) for line in lines[1:] if line.strip()
    ]


def import_e2e(path: Path, *, root: Path = RUNS, suffix: str | None = None) -> Path:
    run = prepare_e2e(*load_e2e(path), command=["eval-import-legacy", "e2e", path.name])
    return write_run(run.manifest, run.items, root=root, suffix=suffix, metrics=run.metrics)
