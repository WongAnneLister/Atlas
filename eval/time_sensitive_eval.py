"""Measure policy version retrieval with the production retriever and gate, without an LLM."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from eval.registry import DatasetEntry, load_registry
from eval.run_record import (
    RUNS,
    DatasetVersion,
    RunItem,
    RunManifest,
    git,
    is_dirty,
    read_run,
    write_run,
)
from eval.schema import TimeSensitiveItem
from eval.stats import wilson_interval
from eval.sweep import production_chunks
from support_agent.config import REPO_ROOT, get_settings
from support_agent.data.doc_models import digest, json_text, write_text
from support_agent.data.policy_versions import PolicyVersions, VersionedPolicy, load_versions
from support_agent.gate.evidence import evaluate
from support_agent.graph.deps import GraphDeps
from support_agent.graph.intents import Intent
from support_agent.graph.nodes.refund import RefundPath
from support_agent.graph.state import ConversationState
from support_agent.orders.models import Order, OrderNotFound

KIND = "time_sensitive"
REPORT = REPO_ROOT / "eval/reports/time_sensitive.md"
METRICS = ("version_hit_at_5", "wrong_version_at_5", "gate_pass", "filters_applied")
TOP_FIVE = 5


class OrderLookup(Protocol):
    def get_order(self, order_id: str, customer_id: str) -> Order: ...


def load_items(entry: DatasetEntry) -> list[TimeSensitiveItem]:
    data = (REPO_ROOT / entry.path).read_bytes()
    if hashlib.sha256(data).hexdigest() != entry.sha256:
        raise ValueError("eval_v2 differs from the registry; run make eval-time-sensitive-build")
    # The v1 prefix stays byte-for-byte unchanged and uses its own record schema.
    return [
        TimeSensitiveItem.model_validate(row)
        for line in data.splitlines()
        if line.strip() and (row := json.loads(line))["group"] == KIND
    ]


def measure(
    item: TimeSensitiveItem,
    entry: VersionedPolicy,
    deps: GraphDeps,
    orders: OrderLookup,
    refund: RefundPath,
) -> RunItem:
    settings = deps.settings
    if item.path == "knowledge":
        as_of = settings.orders.today
        chunks = production_chunks(deps.knowledge_retriever(), item.question, settings)
        gate = evaluate(item.question, chunks, settings.gate)
    else:
        if item.order_id is None or item.customer_id is None:
            raise ValueError(f"{item.id} is missing fixture order identity")
        try:
            order = orders.get_order(item.order_id, item.customer_id)
        except OrderNotFound as exc:
            raise ValueError(f"Dated fixture order {item.order_id} is missing") from exc
        as_of = order.order_date
        result = refund.retrieve_policy(
            ConversationState(
                customer_id=order.customer_id,
                intent=Intent.RETURN_EXCHANGE
                if entry.base_section_id.startswith("returns.")
                else Intent.REFUND_REQUEST,
                order_context={"order": order.model_dump(mode="json")},
            )
        )
        if result.get("retrieval_error_type"):
            raise RuntimeError(f"Refund retrieval failed for {item.id}")
        chunks = result["retrieval"]
        gate = result["gate"]

    gold = entry.section_at(as_of)
    if item.as_of != as_of or item.gold_sections != [gold]:
        raise ValueError(f"{item.id} does not match the policy in force on {as_of}")
    top = [chunk.section_id for chunk in chunks[:TOP_FIVE]]
    wrong = entry.old_id if gold == entry.base_section_id else entry.base_section_id
    return RunItem(
        id=item.id,
        group=item.group,
        answerable=item.answerable,
        metrics={
            "version_hit_at_5": gold in top,
            "wrong_version_at_5": wrong in top,
            "gate_pass": gate.passed,
            "filters_applied": False,
        },
        payload={
            "path": item.path,
            "as_of": as_of.isoformat(),
            "gold_section": gold,
            "top_sections": top,
            "gate_reason": gate.reason,
        },
    )


def collect_run(
    deps: GraphDeps,
    orders: OrderLookup,
    items: list[TimeSensitiveItem],
    versions: PolicyVersions,
    *,
    run_root: Path = RUNS,
    command: Sequence[str] = (),
) -> Path:
    splits = {item.split for item in items}
    if len(splits) != 1:
        raise ValueError("A time-sensitive run must contain items from exactly one split")
    split = splits.pop()
    started_at = datetime.now(UTC)
    sha, dirty = git("rev-parse", "HEAD"), is_dirty()
    settings = deps.settings
    dataset = load_registry()["eval_v2"]
    policies = {entry.base_section_id: entry for entry in versions.entries}
    refund = RefundPath(deps)
    rows = [measure(item, policies[item.version_of], deps, orders, refund) for item in items]
    retrieval = settings.retrieval
    return write_run(
        RunManifest(
            kind=KIND,
            split=split,
            git_sha=sha,
            dirty=dirty,
            config_hash=digest(
                json_text(
                    {
                        "settings": settings.model_dump(mode="json"),
                        "policy_version_spec": versions.model_dump(mode="json"),
                    }
                )
            ),
            models={
                "embedding": f"{retrieval.embedding_model}@{retrieval.embedding_revision}",
                "reranker": f"{retrieval.reranker_model}@{retrieval.reranker_revision}",
            },
            datasets={dataset.name: DatasetVersion(version=dataset.version, sha256=dataset.sha256)},
            started_at=started_at,
            ended_at=datetime.now(UTC),
            seed=settings.eval.stats.seed,
            cost_usd=None,
            cost_note="retrieval and evidence gate only",
            command=list(command),
            source={
                "filters": "off",
                "collection": settings.milvus.collection,
                "build_id": deps.current_build_id(),
                "reranker_device": retrieval.reranker_device,
            },
        ),
        rows,
        root=run_root,
        suffix=uuid4().hex,
    )


def wilson_cell(rows: list[RunItem], metric: str, alpha: float) -> str:
    count = sum(row.metrics[metric] is True for row in rows)
    interval = wilson_interval(count, len(rows), alpha)
    return f"{count}/{len(rows)} {interval.point:.2%} [{interval.low:.2%}, {interval.high:.2%}]"


def write_report(paths: list[Path], output: Path) -> None:
    lines = [
        "# Time-sensitive policy retrieval",
        "",
        "Generated from run records by `make eval-time-sensitive`.",
        "",
        "Version hits and wrong-version hits can both occur in one row.",
        "The gate is evaluated without an LLM. This does not measure decision or answer quality.",
        "",
    ]
    for path in paths:
        run = read_run(path)
        manifest = run.manifest
        if manifest.kind != KIND or run.metrics.bootstrap is None:
            raise ValueError(f"Expected a time-sensitive run with confidence settings: {path}")
        alpha = run.metrics.bootstrap.alpha
        dataset = manifest.datasets["eval_v2"]
        lines.extend(
            [
                f"## {path.name}",
                "",
                f"- Git SHA: `{manifest.git_sha}` (dirty: {manifest.dirty})",
                f"- Config hash: `{manifest.config_hash}`",
                f"- Date (UTC): {manifest.started_at}",
                f"- Dataset: eval_v2 {dataset.version} (`{dataset.sha256}`)",
                f"- Models: {manifest.models}",
                f"- Collection: `{manifest.source['collection']}`"
                f" (build: `{manifest.source['build_id']}`)",
                f"- Filters: {manifest.source['filters']}. Intervals: {(1 - alpha):.0%} Wilson.",
                "",
                "| Split | Path | Items | " + " | ".join(METRICS) + " |",
                "|---|---|---:|" + "---:|" * len(METRICS),
            ]
        )
        for name in ("all", "knowledge", "refund"):
            rows = (
                run.items
                if name == "all"
                else [row for row in run.items if row.payload["path"] == name]
            )
            if rows:
                cells = " | ".join(wilson_cell(rows, metric, alpha) for metric in METRICS)
                lines.append(f"| {manifest.split} | {name} | {len(rows)} | {cells} |")
        lines.append("")
    write_text(output, "\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    args_list = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("dev", "test", "all"), default="all")
    parser.add_argument(
        "--filters",
        choices=("off", "date", "date_category"),
        default="off",
        help="23a supports only --filters off; date and date_category require commit 23",
    )
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--report-from", type=Path, nargs="+", metavar="RUN")
    args = parser.parse_args(args_list)
    if args.filters != "off":
        parser.error("23a supports only --filters off")
    output = REPO_ROOT / args.report
    if args.report_from:
        write_report([REPO_ROOT / path for path in args.report_from], output)
        return 0

    settings = get_settings()
    versions = load_versions(settings.policy_versions)
    items = load_items(load_registry()["eval_v2"])
    splits = ("dev", "test") if args.split == "all" else (args.split,)
    command = ["python", "-m", "eval.time_sensitive_eval", *args_list]
    with GraphDeps(settings) as deps:
        orders = deps.orders()
        paths = [
            collect_run(
                deps,
                orders,
                [item for item in items if item.split == split],
                versions,
                command=command,
            )
            for split in splits
        ]
    write_report(paths, output)
    for path in paths:
        sys.stdout.write(f"{path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
