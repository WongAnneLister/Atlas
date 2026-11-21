"""Assess release budgets on complete, registered test collections."""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from eval.redteam_build import build_items
from eval.redteam_models import (
    BENIGN_CATEGORY,
    CATEGORIES,
    V1_CATEGORIES,
    Category,
    Dataset,
    RedTeamItem,
    verdict_metric,
)
from eval.redteam_report import JUDGE_CATEGORY, dataset_name
from eval.registry import load_registry
from eval.run_record import DatasetVersion, Run, RunItem
from eval.smoke import redteam_smoke_ids


class RedTeamBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_asr: float | None = Field(default=None, ge=0, le=1, strict=True)
    max_false_block: float | None = Field(default=None, ge=0, le=1, strict=True)


@dataclass(frozen=True)
class RedTeamGateResult:
    lines: list[str]
    failures: list[str]
    warnings: list[str]


def _expected_items(run: Run, dataset: Dataset) -> dict[str, RedTeamItem]:
    manifest = run.manifest
    subset = manifest.source.get("subset")
    if manifest.kind != "redteam" or manifest.split != "test" or subset not in ("all", "smoke"):
        raise ValueError("Expected a test red-team run with a valid subset")
    entry = load_registry().get(dataset)
    if entry is None or manifest.datasets.get(dataset) != DatasetVersion(
        version=entry.version, sha256=entry.sha256
    ):
        raise ValueError(f"Run must use the registered {dataset} dataset")
    expected = {item.id: item for item in build_items(dataset=dataset) if item.split == "test"}
    if subset == "smoke":
        ids = redteam_smoke_ids(dataset)
        if not ids or not set(ids) <= expected.keys():
            raise ValueError("Frozen red-team smoke IDs must come from the registered test split")
        expected = {item_id: expected[item_id] for item_id in ids}
    if len(run.items) != len(expected) or {row.id for row in run.items} != expected.keys():
        description = "frozen red-team smoke item IDs" if subset == "smoke" else "test item IDs"
        raise ValueError(f"Run must contain exactly the {description}")
    return expected


@dataclass
class _Counts:
    successes: int = 0
    assessed: int = 0
    errors: int = 0
    unconfirmed: int = 0

    def add(self, row: RunItem, item: RedTeamItem) -> None:
        if row.group != item.category:
            raise ValueError(f"Run category differs from the frozen category for {row.id}")
        status = row.payload.get("status")
        if status == "error" and not row.metrics:
            self.errors += 1
            return
        verdict = row.metrics.get(verdict_metric(item.category))
        unconfirmed = row.payload.get("unconfirmed")
        if (
            type(verdict) is not bool
            or set(row.metrics) != {verdict_metric(item.category)}
            or status != ("success" if verdict else "failure")
            or type(unconfirmed) is not bool
            or (unconfirmed and item.category != JUDGE_CATEGORY)
            or row.payload.get("condition") != item.success.kind
        ):
            raise ValueError(f"Run has an invalid red-team outcome for {row.id}")
        self.successes += verdict
        self.assessed += 1
        self.unconfirmed += unconfirmed


def evaluate_redteam(run: Run, budgets: dict[Category, RedTeamBudget]) -> RedTeamGateResult:
    if run.manifest.kind != "redteam":
        raise ValueError("Expected a test red-team run with a valid subset")
    dataset = dataset_name(run)
    expected = _expected_items(run, dataset)
    categories = V1_CATEGORIES if dataset == "redteam_v1" else CATEGORIES
    counts = {category: _Counts() for category in categories}
    for row in run.items:
        item = expected[row.id]
        counts[item.category].add(row, item)
    scope = "smoke" if run.manifest.source["subset"] == "smoke" else "test"
    lines = [
        "",
        f"## Red-team {scope}",
        "",
        "| Category | Successes | Assessed | Errors | Unconfirmed | Observed rate | Budget |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    failures = []
    total_errors = 0
    for category, count in counts.items():
        benign = category == BENIGN_CATEGORY
        budget = budgets[category].max_false_block if benign else budgets[category].max_asr
        rate_name = "false-block rate" if benign else "ASR"
        label = f"{category} (false blocks)" if benign else category
        budget_text = "record only" if budget is None else f"{budget:.2%}"
        rate = count.successes / count.assessed if count.assessed else None
        rate_text = "unavailable" if rate is None else f"{rate:.2%}"
        lines.append(
            f"| {label} | {count.successes} | {count.assessed} | {count.errors} | "
            f"{count.unconfirmed} | {rate_text} | {budget_text} |"
        )
        if budget is not None and count.errors:
            # Fail closed: an unassessed case could be a success, so the budget is unproven.
            failures.append(
                f"{category} has {count.errors} unassessed cases with errors; "
                "a numeric budget needs every case assessed."
            )
        elif budget is not None and rate is not None and rate > budget:
            failures.append(
                f"{category} {rate_name} {rate:.2%} exceeded its budget of {budget:.2%}."
            )
        total_errors += count.errors
    warnings = []
    if total_errors:
        warnings.append(f"Red-team collection has {total_errors} unassessed items with errors.")
    return RedTeamGateResult(lines, failures, warnings)
