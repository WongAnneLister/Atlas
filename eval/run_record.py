"""Typed manifests, local per-item results, and publishable aggregate metrics."""

import shutil
import subprocess
from collections import defaultdict
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from eval.stats import Interval, Statistic, bootstrap_ci, rule_of_three_upper, wilson_interval
from support_agent.config import REPO_ROOT, EvalStatsSettings, get_settings

RUNS = REPO_ROOT / "eval/runs"
StatisticName = Literal["mean", "p50", "p95", "macro_precision", "macro_recall"]
SAFE_COMPONENT = r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$"


class DatasetVersion(BaseModel):
    version: str | None
    sha256: str


class RunManifest(BaseModel):
    kind: str = Field(pattern=SAFE_COMPONENT)
    split: str = Field(pattern=SAFE_COMPONENT)
    git_sha: str = Field(pattern=SAFE_COMPONENT)
    config_hash: str
    models: dict[str, str]
    datasets: dict[str, DatasetVersion]
    seed: int | None
    dirty: bool | None
    started_at: datetime | None
    ended_at: datetime | None
    cost_usd: float | None
    cost_note: str | None
    command: list[str]
    source: dict[str, Any] = Field(default_factory=dict)


class RunItem(BaseModel):
    id: str
    metrics: dict[str, float | bool] = Field(default_factory=dict)
    group: str | None = None
    answerable: bool | None = None
    handoff_reason: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class MetricSummary(BaseModel):
    interval: Interval
    n: int = Field(gt=0)
    count: int | None = None
    wilson_upper: float | None = None
    rule_of_three_upper: float | None = None


class RunMetrics(BaseModel):
    metrics: dict[str, MetricSummary]
    statistics: dict[str, StatisticName] = Field(default_factory=dict)
    bootstrap: EvalStatsSettings | None = None


class Run(BaseModel):
    manifest: RunManifest
    items: list[RunItem]
    metrics: RunMetrics


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True).strip()


def is_dirty() -> bool:
    return bool(git("status", "--porcelain"))


def dataset_version(sha256: str) -> dict[str, DatasetVersion]:
    """Resolve a frozen digest without claiming a version for unregistered data."""
    from eval.registry import load_registry

    matches = {
        name: DatasetVersion(version=entry.version, sha256=sha256)
        for name, entry in load_registry().items()
        if entry.sha256 == sha256
    }
    return matches or {"unregistered": DatasetVersion(version=None, sha256=sha256)}


def resolve_statistic(name: StatisticName) -> Statistic:
    if name in ("macro_precision", "macro_recall"):
        from eval.intent_run_metrics import intent_macro_stat

        return partial(intent_macro_stat, precision=name == "macro_precision")
    return name


def summarize_metrics(
    items: list[RunItem], statistics: dict[str, StatisticName] | None = None
) -> RunMetrics:
    grouped: dict[str, list[float | bool]] = defaultdict(list)
    for item in items:
        for name, value in item.metrics.items():
            grouped[name].append(value)
    stats = get_settings().eval.stats.model_dump()
    statistics = statistics or {}
    return RunMetrics(
        metrics={
            name: summarize(values, resolve_statistic(statistics.get(name, "mean")), **stats)
            for name, values in sorted(grouped.items())
        },
        statistics=statistics,
        bootstrap=EvalStatsSettings.model_validate(stats),
    )


def confidence_level(metrics: RunMetrics) -> float:
    return 1 - (metrics.bootstrap or get_settings().eval.stats).alpha


def summarize(
    values: list[float | bool], stat: Statistic = "mean", **bootstrap_options: Any
) -> MetricSummary:
    n = len(values)
    count = sum(bool(value) for value in values) if all(type(v) is bool for v in values) else None
    return MetricSummary(
        interval=bootstrap_ci(values, stat, **bootstrap_options),
        n=n,
        count=count,
        wilson_upper=wilson_interval(0, n, bootstrap_options.get("alpha", 0.05)).high
        if count == 0
        else None,
        rule_of_three_upper=rule_of_three_upper(n) if count == 0 else None,
    )


def format_summary(summary: MetricSummary, *, rate: bool = True) -> str:
    fmt = ".2%" if rate else ".4f"
    interval = summary.interval
    count = f"{summary.count}/{summary.n} · " if summary.count is not None else ""
    result = f"{count}{interval.point:{fmt}} [{interval.low:{fmt}}, {interval.high:{fmt}}]"
    if summary.wilson_upper is not None and summary.rule_of_three_upper is not None:
        result += (
            f" (upper bounds: {summary.rule_of_three_upper:.1%} rule of three, "
            f"{summary.wilson_upper:.1%} Wilson)"
        )
    return result


def _check_items(items: list[RunItem]) -> None:
    if not items or len({item.id for item in items}) != len(items):
        raise ValueError("Run must contain unique item IDs and at least one item")


def write_run(
    manifest: RunManifest,
    items: list[RunItem],
    *,
    root: Path = RUNS,
    suffix: str | None = None,
    metrics: RunMetrics | None = None,
) -> Path:
    _check_items(items)
    if suffix and (not suffix.isascii() or not suffix.replace("-", "").replace("_", "").isalnum()):
        raise ValueError("Invalid run suffix")
    date = manifest.started_at or manifest.ended_at
    if date is None and manifest.source.get("date") not in (None, "pending"):
        date = datetime.fromisoformat(manifest.source["date"])
    date = date or datetime.now(UTC)
    run_id = f"{manifest.kind}-{manifest.split}-{date:%Y%m%d}-{manifest.git_sha[:8]}"
    path = root / (f"{run_id}-{suffix}" if suffix else run_id)
    metrics = metrics if metrics is not None else summarize_metrics(items)
    path.mkdir(parents=True, exist_ok=False)
    try:
        (path / "items.jsonl").write_text(
            "".join(item.model_dump_json() + "\n" for item in items), encoding="utf-8"
        )
        (path / "metrics.json").write_text(
            metrics.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        (path / "manifest.json").write_text(
            manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
    except BaseException:
        shutil.rmtree(path)
        raise
    return path


def read_run(path: Path) -> Run:
    manifest = RunManifest.model_validate_json((path / "manifest.json").read_bytes())
    metrics = RunMetrics.model_validate_json((path / "metrics.json").read_bytes())
    items = [
        RunItem.model_validate_json(line)
        for line in (path / "items.jsonl").read_bytes().splitlines()
        if line.strip()
    ]
    _check_items(items)
    return Run(manifest=manifest, items=items, metrics=metrics)
