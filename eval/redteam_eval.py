"""Collect or replay the registered fixture-only evaluation through the Atlas ASGI app."""

import argparse
import asyncio
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage

from eval.e2e_endpoint import endpoint_host
from eval.e2e_eval import _model_names
from eval.judge import JudgeDecision
from eval.redteam_build import DEFAULT_DATASET, load_items
from eval.redteam_canaries import DEFAULT_SEED
from eval.redteam_fixtures import isolated_settings
from eval.redteam_models import DATASETS, Dataset, RedTeamItem, verdict_metric
from eval.redteam_report import (
    export_review,
    local_output,
    publish_text,
    redteam_metrics,
    render_report,
)
from eval.redteam_runner import ItemOutcome, JudgeInput, run
from eval.registry import file_hash, load_registry
from eval.run_record import RUNS, DatasetVersion, Run, RunItem, RunManifest, git, is_dirty, read_run
from eval.smoke import redteam_smoke_ids
from support_agent.config import REPO_ROOT, get_settings
from support_agent.data.doc_models import digest, json_text
from support_agent.graph.deps import GraphDeps

DEFAULT_REPORT = REPO_ROOT / "eval/reports/redteam.md"
JUDGE_PROMPT = REPO_ROOT / "eval/prompts/redteam_commitments.md"


def _select(
    items: list[RedTeamItem], split: str, subset: str, *, dataset: Dataset = "redteam_v1"
) -> list[RedTeamItem]:
    chosen = [item for item in items if item.split == split]
    if subset == "smoke":
        if split != "test":
            raise ValueError("Red-team smoke is a test split")
        ids = redteam_smoke_ids(dataset)
        by_id = {item.id: item for item in chosen}
        if not ids or len(set(ids)) != len(ids) or any(identity not in by_id for identity in ids):
            raise ValueError("Invalid frozen red-team smoke IDs")
        chosen = [by_id[identity] for identity in ids]
    if not chosen:
        raise ValueError("No items match the requested red-team split")
    return chosen


def _judge(deps: GraphDeps) -> Callable[[JudgeInput], JudgeDecision]:
    prompt = JUDGE_PROMPT.read_text(encoding="utf-8")

    def evaluate(payload: JudgeInput) -> JudgeDecision:
        response, _ = deps.models.invoke(
            "answer",
            "main",
            [SystemMessage(content=prompt), HumanMessage(content=payload.model_dump_json())],
        )
        if not isinstance(response.content, str):
            raise ValueError("The judge did not return a JSON verdict")
        return JudgeDecision.model_validate_json(response.content)

    return evaluate


def _project(observations: list[ItemOutcome], items: list[RedTeamItem]) -> list[RunItem]:
    expected = {item.id: item for item in items}
    if (
        len(observations) != len(expected)
        or {row.item_id for row in observations} != set(expected)
        or any(row.category != expected[row.item_id].category for row in observations)
    ):
        raise ValueError("Collector returned incomplete or duplicate observations")
    return [
        RunItem(
            id=row.item_id,
            group=row.category,
            metrics=(
                {}
                if row.status == "error"
                else {verdict_metric(row.category): row.status == "success"}
            ),
            payload={
                **row.model_dump(mode="json"),
                "condition": expected[row.item_id].success.kind,
                "unconfirmed": row.judge_used,
                # Review needs the attack text next to the reply. items.jsonl stays local.
                "turn_texts": [turn.text for turn in expected[row.item_id].turns],
            },
        )
        for row in observations
    ]


def _collect(args: argparse.Namespace, arguments: list[str]) -> tuple[Run, Path]:
    settings = get_settings()
    entry = load_registry()[args.dataset]
    source = REPO_ROOT / entry.path
    if file_hash(source) != entry.sha256:
        raise ValueError("Red-team cases do not match the registered dataset hash")
    items = _select(load_items(source), args.split, args.subset, dataset=args.dataset)
    started = datetime.now(UTC)
    sha = git("rev-parse", "HEAD")
    dirty = is_dirty()
    run_dir = (
        args.run_root.resolve()
        / f"redteam-{args.split}-{started:%Y%m%d}-{sha[:8]}-{uuid4().hex[:8]}"
    )
    run_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    isolated = isolated_settings(
        settings, run_dir, request_count=1 + sum(len(item.turns) for item in items)
    )
    effective = isolated.model_dump(mode="json")
    effective["orders"]["db_path"] = "run-local"
    models = _model_names(isolated)
    if any(item.category == "policy_fabrication" for item in items):
        models["judge"] = models["main"]
    with GraphDeps(isolated) as judge_deps:
        observations = asyncio.run(
            run(items, settings=settings, run_dir=run_dir, judge=_judge(judge_deps))
        )
    rows = _project(observations, items)
    manifest = RunManifest(
        kind="redteam",
        split=args.split,
        git_sha=sha,
        config_hash=digest(json_text(effective)),
        models=models,
        datasets={args.dataset: DatasetVersion(version=entry.version, sha256=entry.sha256)},
        seed=DEFAULT_SEED,
        dirty=dirty,
        started_at=started,
        ended_at=datetime.now(UTC),
        cost_usd=None,
        cost_note="usage not aggregated across isolated conversations",
        command=["python", "-m", "eval.redteam_eval", *arguments],
        source={
            "subset": args.subset,
            "endpoint_host": endpoint_host(isolated.llm),
            "dataset_versions": {
                record.name: f"{record.repo_id}@{record.revision}"
                for record in isolated.data.sources
            },
        },
    )
    metrics = redteam_metrics(rows, isolated.eval.stats)
    publish_text(run_dir / "items.jsonl", "".join(f"{row.model_dump_json()}\n" for row in rows))
    publish_text(run_dir / "metrics.json", metrics.model_dump_json(indent=2) + "\n")
    publish_text(run_dir / "manifest.json", manifest.model_dump_json(indent=2) + "\n")
    return Run(manifest=manifest, items=rows, metrics=metrics), run_dir


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=DATASETS, default=DEFAULT_DATASET)
    parser.add_argument("--split", choices=["dev", "test"], default="test")
    parser.add_argument("--subset", choices=["all", "smoke"], default="all")
    parser.add_argument("--run-root", type=Path, default=RUNS)
    parser.add_argument("--run-pointer", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--review-csv", type=Path)
    parser.add_argument("--run-dir", type=Path, help="render a saved run offline")
    args = parser.parse_args(arguments)
    try:
        if args.report:
            local_output(args.report, ".md")
        if args.review_csv:
            local_output(args.review_csv, ".csv")
        if args.run_pointer:
            local_output(args.run_pointer, "", ".txt")
        if args.run_dir:
            result = read_run(args.run_dir)
            if args.review_csv:
                export_review(result.items, args.review_csv)
        else:
            result, run_dir = _collect(args, arguments)
            export_review(result.items, args.review_csv or run_dir / "review.csv")
            if args.run_pointer:
                publish_text(args.run_pointer, f"{run_dir}\n")
        report = args.report or DEFAULT_REPORT
        if not args.report and result.manifest.source.get("subset") == "smoke":
            report = RUNS / "redteam-smoke.md"
        elif not args.report and result.manifest.split == "dev":
            report = RUNS / "redteam-dev.md"
        render_report(result, report)
    except (OSError, ValueError) as error:
        parser.error(f"Red-team setup or record validation failed ({type(error).__name__})")
    return int(any(row.payload["status"] == "error" for row in result.items))


if __name__ == "__main__":
    raise SystemExit(main())
