"""Shared provenance and interval tables for the v1 experiment renderers."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eval.run_record import DatasetVersion, Run, RunManifest, format_summary
from support_agent.config import Settings, get_settings
from support_agent.data.doc_models import write_text


def has_complete_prices(settings: Settings) -> bool:
    return any(
        rate.input_per_million_usd is not None and rate.output_per_million_usd is not None
        for rate in settings.costs.prices.values()
    )


def manifest_for_core(
    kind: str,
    split: str,
    metadata: dict[str, Any],
    datasets: dict[str, DatasetVersion],
    models: dict[str, str],
    command: list[str],
    dirty: bool | None,
) -> RunManifest:
    settings = get_settings()
    return RunManifest(
        kind=kind,
        split=split,
        git_sha=metadata["git_sha"],
        config_hash=metadata["config_hash"],
        models=models,
        datasets=datasets,
        seed=settings.eval.stats.seed,
        dirty=dirty,
        started_at=datetime.fromisoformat(metadata["date"]),
        ended_at=datetime.now(UTC) if dirty is not None else None,
        cost_usd=None,
        cost_note=(
            "price not set"
            if not has_complete_prices(settings)
            else "token usage was not recorded"
            if kind == "intent"
            else "no chat model calls"
        ),
        command=command,
        source={"metadata": metadata, "statistics": settings.eval.stats.model_dump()},
    )


def write_intervals(path: Path, run: Run, names: list[str]) -> None:
    level = 1 - run.manifest.source["statistics"]["alpha"]
    lines = [
        "",
        f"## Bootstrap intervals ({level:.0%})",
        "",
        "| Metric | Estimate and interval |",
        "|---|---:|",
    ]
    for name in names:
        if (metric := run.metrics.metrics.get(name)) is not None:
            rate = not name.endswith(("latency_s", "latency_p95"))
            lines.append(f"| {name} | {format_summary(metric, rate=rate)} |")
    write_text(path, path.read_text(encoding="utf-8") + "\n".join(lines) + "\n")
