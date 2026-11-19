"""Persist the scored inputs and selected threshold for offline sweep replay."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from eval import sweep
from eval.core_run_reporting import has_complete_prices, write_intervals
from eval.legacy_core import RUNS, dataset_version
from eval.run_record import RunItem, RunManifest, read_run, write_run
from eval.sweep import GateScore, GateScoreMetadata
from support_agent.config import get_settings

ScoreCache = tuple[GateScoreMetadata, list[GateScore]]


def _at_threshold(score: GateScore, threshold: float, key: str) -> dict[str, bool]:
    passed = not score.vetoed and score.score >= threshold
    metrics = {f"{key}.pass_rate": passed}
    if score.answerable:
        metrics[f"{key}.false_reject"] = not passed
    else:
        metrics[f"{key}.false_accept"] = passed
    return metrics


def score_run_items(records: list[GateScore], selected: float | None) -> list[RunItem]:
    items = []
    for record in records:
        metrics = _at_threshold(record, selected, record.split) if selected is not None else {}
        if record.split == "dev":
            for cutoff in sweep.thresholds():
                metrics.update(_at_threshold(record, cutoff, f"dev@{cutoff:.2f}"))
        items.append(
            RunItem(
                id=f"{record.split}/{record.id}",
                group=record.group,
                answerable=record.answerable,
                metrics=metrics,
                payload=record.model_dump(mode="json"),
            )
        )
    return items


def save_sweep(
    dev: ScoreCache,
    test: ScoreCache | None,
    rule: str,
    command: list[str],
    *,
    root: Path = RUNS,
    suffix: str | None = None,
    dirty: bool | None = None,
    started_at: datetime | None = None,
    config_hash: str | None = None,
    git_sha: str | None = None,
) -> Path:
    dev_meta, dev_rows = dev
    records = list(dev_rows)
    test_meta = None
    if test:
        test_meta, test_rows = test
        bound_fields = ("config_hash", "eval_file_hash", "corpus_hash", "models")
        if any(getattr(dev_meta, key) != getattr(test_meta, key) for key in bound_fields):
            raise ValueError("Dev and test score caches must agree on their eval and score config")
        records.extend(test_rows)
    if dev_meta.split != "dev" or any(row.split != "dev" for row in dev_rows):
        raise ValueError("Only dev inputs can be used to select a threshold")
    if test and (test[0].split != "test" or any(row.split != "test" for row in test[1])):
        raise ValueError("Expected test split in held-out score cache")
    selected = sweep.select_threshold(dev_rows, rule)
    settings = get_settings()
    manifest = RunManifest(
        kind="sweep",
        split="all" if test else "dev",
        git_sha=git_sha or dev_meta.git_sha,
        config_hash=config_hash or dev_meta.config_hash,
        models=dev_meta.models,
        datasets={"eval_v1": dataset_version("eval_v1", dev_meta.eval_file_hash)},
        seed=settings.eval.stats.seed,
        dirty=dirty,
        started_at=started_at or datetime.fromisoformat(dev_meta.date),
        ended_at=datetime.now(UTC) if started_at is not None else None,
        cost_usd=None,
        cost_note="no chat model calls" if has_complete_prices(settings) else "price not set",
        command=command,
        source={
            "dev_metadata": dev_meta.model_dump(mode="json"),
            "test_metadata": test_meta.model_dump(mode="json") if test_meta else None,
            "threshold": selected,
            "rule": rule,
            "statistics": settings.eval.stats.model_dump(),
        },
    )
    return write_run(manifest, score_run_items(records, selected), root=root, suffix=suffix)


def import_sweep(
    dev_path: Path,
    test_path: Path | None,
    *,
    rule: str = "lowest",
    root: Path = RUNS,
    suffix: str | None = None,
) -> Path:
    paths = [dev_path.name] + ([test_path.name] if test_path else [])
    return save_sweep(
        sweep.load_scores(dev_path),
        sweep.load_scores(test_path) if test_path else None,
        rule,
        ["eval-import-legacy", "sweep", *paths, "--rule", rule],
        root=root,
        suffix=suffix,
    )


def render_sweep(run_path: Path, report_path: Path, plot_path: Path | None = None) -> float | None:
    run = read_run(run_path)
    if run.manifest.kind != "sweep":
        raise ValueError("Expected a sweep run")
    source = run.manifest.source
    metadata = GateScoreMetadata.model_validate(source["dev_metadata"])
    test_metadata = (
        GateScoreMetadata.model_validate(source["test_metadata"])
        if source["test_metadata"]
        else None
    )
    records = [GateScore.model_validate(item.payload) for item in run.items]
    dev = [r for r in records if r.split == "dev"]
    test = [r for r in records if r.split == "test"]
    selected = source["threshold"]
    sweep.write_report(metadata, dev, selected, test_metadata, test, report_path, source["rule"])
    write_intervals(
        report_path,
        run,
        [name for name in run.metrics.metrics if name.startswith(("dev.", "test."))],
    )
    if plot_path:
        sweep.write_plot(dev, plot_path, selected)
    return selected
