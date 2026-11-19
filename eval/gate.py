"""Compare a frozen smoke run with main and enforce the release rules."""

import argparse
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from eval.paired import Comparison, MetricRule, compare, comparison_lines
from eval.registry import load_registry
from eval.run_record import (
    DatasetVersion,
    Run,
    RunItem,
    RunManifest,
    RunMetrics,
    git,
    is_dirty,
    read_run,
)
from eval.smoke import SMOKE_PATH, SmokeSpec
from support_agent.config import REPO_ROOT
from support_agent.data.doc_models import write_text

RULES = REPO_ROOT / "eval/gate_rules.yaml"
BASELINE = REPO_ROOT / "eval/baselines/main.json"


class GateRules(BaseModel):
    false_accept_max: Literal[0]
    promotion_max_error_rate: float = Field(ge=0, le=1)
    metrics: dict[str, MetricRule]
    redteam: list[str]
    comparison_lower_is_better: list[str]


class BaselineItem(BaseModel):
    group: str
    answerable: bool
    handoff_reason: str | None
    metrics: dict[str, float | bool]


class Baseline(BaseModel):
    run_id: str
    manifest: RunManifest
    outcomes: dict[str, BaselineItem] = Field(min_length=1)
    metrics: RunMetrics


@dataclass(frozen=True)
class GateResult:
    false_accepts: int
    no_answer: int
    comparisons: list[Comparison]
    failures: list[str]
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures

    def markdown(self) -> str:
        status = "Passed" if self.passed else "Failed"
        return "\n".join(
            [
                f"# Eval release gate — {status}",
                "",
                f"No-answer false accepts: {self.false_accepts}/{self.no_answer}",
                "",
                *[f"- {failure}" for failure in self.failures],
                *[f"- {warning}" for warning in self.warnings],
                "",
                *comparison_lines(self.comparisons),
                "",
            ]
        )


def load_rules(path: Path = RULES) -> GateRules:
    return GateRules.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _smoke_dataset(run: Run) -> DatasetVersion:
    manifest = run.manifest
    dataset = manifest.datasets.get("smoke")
    if (
        manifest.kind != "smoke"
        or manifest.split != "test"
        or dataset is None
        or not dataset.version
    ):
        raise ValueError("Expected a versioned test smoke run")
    return dataset


def check_frozen_smoke(run: Run) -> None:
    spec = SmokeSpec.model_validate(yaml.safe_load(SMOKE_PATH.read_text(encoding="utf-8")))
    expected = set(spec.item_ids)
    if len(run.items) != len(expected) or {row.id for row in run.items} != expected:
        raise ValueError("Run must contain exactly the frozen smoke item IDs")
    entry = load_registry()["smoke"]
    if _smoke_dataset(run) != DatasetVersion(version=entry.version, sha256=entry.sha256):
        raise ValueError("Run must use the registered smoke dataset")
    for row in run.items:
        group = row.id.partition("-")[0]
        if row.group != group or row.answerable != (group != "no_answer"):
            raise ValueError(f"Smoke labels differ for {row.id}")


def _check_metric_coverage(run: Run, rules: GateRules) -> None:
    expected = {
        "false_accept": False,
        "false_reject": True,
        "graph_recall_at_5": True,
        "citation_validity": True,
    }
    for row in run.items:
        for name in rules.metrics:
            required = name not in expected or row.answerable is expected[name]
            if (name in row.metrics) != required:
                raise ValueError(f"{name} requires the same observations as the frozen benchmark")


def _false_accepts(run: Run) -> tuple[int, int]:
    no_answer = [row for row in run.items if row.group == "no_answer"]
    if not no_answer or any(row.answerable is not False for row in no_answer):
        raise ValueError("Smoke run requires labeled no-answer items")
    if any(type(row.metrics.get("false_accept")) is not bool for row in no_answer):
        raise ValueError("Smoke run is missing a binary false-accept outcome")
    return sum(row.metrics["false_accept"] is True for row in no_answer), len(no_answer)


def evaluate(run: Run, baseline: Run, rules: GateRules) -> GateResult:
    if _smoke_dataset(run) != _smoke_dataset(baseline):
        raise ValueError("Smoke dataset versions or hashes differ")
    false_accepts, no_answer = _false_accepts(run)
    comparisons = compare(baseline, run, rules.metrics, strict=True)
    _check_metric_coverage(run, rules)
    _check_metric_coverage(baseline, rules)
    worse = [row.name for row in comparisons if row.verdict == "worse"]
    failures = [
        f"{name} showed a significant regression." for name in worse if rules.metrics[name].blocking
    ]
    warnings = [
        f"{name} showed a significant regression (report only; does not block)."
        for name in worse
        if not rules.metrics[name].blocking
    ]
    if false_accepts > rules.false_accept_max:
        failures.insert(0, "The smoke run accepted a no-answer item.")
    return GateResult(false_accepts, no_answer, comparisons, failures, warnings)


ERROR_FIELDS = ("classification_error_type", "retrieval_error_type", "answer_error_type")


def dependency_errors(run: Run) -> Counter[str]:
    """Count items whose graph run hit a dependency or model-call error, by error type."""
    errors: Counter[str] = Counter()
    for row in run.items:
        kinds = {str(row.payload[name]) for name in ERROR_FIELDS if row.payload.get(name)}
        if row.handoff_reason in {"retrieval_error", "answer_error"} and not kinds:
            kinds = {row.handoff_reason}
        errors.update(sorted(kinds)[:1])
    return errors


def check_dependency_errors(run: Run, rules: GateRules) -> None:
    errors = dependency_errors(run)
    count = sum(errors.values())
    if count > rules.promotion_max_error_rate * len(run.items):
        kinds = ", ".join(f"{kind} x{n}" for kind, n in errors.most_common())
        raise ValueError(
            f"Run has dependency errors on {count}/{len(run.items)} items ({kinds}); "
            "fix the dependency and collect a new run"
        )


def read_baseline(path: Path) -> Run:
    baseline = Baseline.model_validate_json(path.read_bytes())
    return Run(
        manifest=baseline.manifest,
        items=[
            RunItem(id=item_id, **item.model_dump()) for item_id, item in baseline.outcomes.items()
        ],
        metrics=baseline.metrics,
    )


def promote(run: Run, run_id: str, path: Path) -> None:
    if git("branch", "--show-current") != "main":
        raise ValueError("Promote baselines from main")
    if is_dirty():
        raise ValueError("Baseline promotion requires a clean working tree")
    if run.manifest.git_sha != git("rev-parse", "HEAD") or run.manifest.dirty is not False:
        raise ValueError("Baseline run must have been collected on clean HEAD")
    check_frozen_smoke(run)
    rules = load_rules()
    check_dependency_errors(run, rules)
    result = evaluate(run, run, rules)
    if not result.passed:
        raise ValueError("The smoke run violates the release rules")
    baseline = Baseline(
        run_id=run_id,
        manifest=run.manifest,
        metrics=run.metrics,
        outcomes={
            row.id: BaselineItem(
                group=row.group,
                answerable=row.answerable,
                handoff_reason=row.handoff_reason,
                metrics=row.metrics,
            )
            for row in run.items
        },
    )
    write_text(path, baseline.model_dump_json(indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "promote"])
    parser.add_argument("run", type=Path)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "check" and not args.baseline.is_file():
            text, status = "# Eval release gate\n\nNo baseline. Promote a smoke run on main.\n", 2
        elif args.action == "promote":
            promote(read_run(args.run), args.run.name, args.baseline)
            text, status = f"Promoted {args.run.name} to {args.baseline}\n", 0
        else:
            run, baseline = read_run(args.run), read_baseline(args.baseline)
            check_frozen_smoke(run)
            check_frozen_smoke(baseline)
            result = evaluate(run, baseline, load_rules())
            text, status = result.markdown(), int(not result.passed)
    except (ValueError, OSError) as error:
        text, status = f"# Eval release gate — Failed\n\n{error}\n", 1
    if args.output:
        write_text(args.output, text)
    sys.stdout.write(text)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
