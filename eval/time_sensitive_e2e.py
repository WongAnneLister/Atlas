"""Run the real graph on the dated refund cases and check the policy version it relies on.

Each `path: refund` item in eval_v2 names one fixture order of `CUST-TS01`. The refund path
reads the policy date only from the stored order, so the item's question text does not drive
retrieval. This evaluator sends two fixed customer requests per order instead: a plain refund
request, and one that claims a purchase month on the other side of the policy change. Both must
use the stored order date. Orders, refunds and the index registry are read from a scratch copy
of the configured SQLite file; checkpoints stay in memory. The dev database is never written.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from eval.e2e_eval import _model_names
from eval.registry import load_registry
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
from eval.time_sensitive_eval import load_items
from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.data.doc_models import digest, json_text, write_text
from support_agent.data.policy_versions import PolicyVersions, load_versions
from support_agent.db.engine import sqlite_path
from support_agent.graph.build import build_graph
from support_agent.graph.deps import GraphDeps

KIND = "time_sensitive_e2e"
REPORT = REPO_ROOT / "eval/reports/time_sensitive_e2e.md"
NOTICE_PREFIX = "Your order was placed on"
REQUESTS = {
    "plain": "I want to return my Generic store order {order_id} for a refund.",
    "claimed_date": "I bought it in {claimed}. Please refund my Generic store order {order_id}.",
}
METRICS = (
    "refund_path",
    "filter_uses_order_date",
    "cites_gold_version",
    "cites_wrong_version",
    "notice_correct",
)


class Graph(Protocol):
    def invoke(self, value: Any, config: dict[str, Any]) -> dict[str, Any]: ...


def claimed_month(order_date: date, change: date) -> str:
    """A purchase month on the other side of the policy change from the stored date."""
    return "August" if order_date >= change else "October"


def run_conversation(graph: Graph, question: str, customer_id: str) -> dict[str, Any]:
    config = {"configurable": {"thread_id": f"{KIND}-{uuid4().hex}"}}
    result = graph.invoke(
        {"messages": [HumanMessage(content=question)], "customer_id": customer_id}, config
    )
    while result.get("__interrupt__"):
        # The order id is in the request; a picker here is a routing outcome, not a choice.
        result = graph.invoke(Command(resume="none"), config)
    return result


def _field(value: Any, name: str) -> Any:
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def score(
    item: TimeSensitiveItem,
    request: str,
    result: dict[str, Any],
    versions: PolicyVersions,
) -> RunItem:
    entry = next(e for e in versions.entries if e.base_section_id == item.version_of)
    gold = item.gold_sections[0]
    wrong = entry.old_id if gold == entry.base_section_id else entry.base_section_id
    cited = [str(_field(c, "section_id")) for c in result.get("citations", [])]
    filters = result.get("filters")
    as_of = _field(filters, "as_of") if filters is not None else None
    trace = list(result.get("trace", []))
    answer = str(result.get("answer", ""))
    expected_notice = gold == entry.old_id
    present = answer.startswith(NOTICE_PREFIX)
    decision = result.get("refund_decision") or {}
    handoff = result.get("handoff")
    reason = _field(handoff, "reason") if handoff is not None else None
    return RunItem(
        id=f"{item.id}:{request}",
        group=item.group,
        answerable=item.answerable,
        handoff_reason=str(getattr(reason, "value", reason)) if reason is not None else None,
        metrics={
            "refund_path": "refund_retrieve" in trace,
            "filter_uses_order_date": as_of is not None and str(as_of) == item.as_of.isoformat(),
            "cites_gold_version": gold in cited,
            "cites_wrong_version": wrong in cited,
            "notice_correct": present == expected_notice,
        },
        payload={
            "request": request,
            "order_id": item.order_id,
            "order_date": item.as_of.isoformat(),
            "gold_section": gold,
            "expected_notice": expected_notice,
            "notice_present": present,
            "filters_applied": bool(result.get("filters_applied")),
            "cited_sections": cited,
            "decision": _field(decision, "eligible"),
            "intent": str(getattr(result.get("intent"), "value", result.get("intent"))),
            "trace": trace,
        },
    )


def collect(
    graph: Graph,
    items: Sequence[TimeSensitiveItem],
    versions: PolicyVersions,
) -> list[RunItem]:
    rows = []
    for item in items:
        if item.order_id is None or item.customer_id is None:
            raise ValueError(f"{item.id} is not a refund case")
        entry = next(e for e in versions.entries if e.base_section_id == item.version_of)
        for request, template in REQUESTS.items():
            question = template.format(
                order_id=item.order_id, claimed=claimed_month(item.as_of, entry.effective_from)
            )
            result = run_conversation(graph, question, item.customer_id)
            rows.append(score(item, request, result, versions))
    return rows


def scratch_settings(settings: Settings, folder: Path) -> Settings:
    """Copy the configured SQLite file so refund writes never reach the dev database."""
    if settings.db.backend != "sqlite":
        raise ValueError("The end-to-end refund evaluator runs on the SQLite backend only")
    target = folder / "orders.sqlite"
    shutil.copy2(sqlite_path(settings), target)
    scratch = settings.model_copy(deep=True)
    scratch.orders.db_path = str(target)
    scratch.graph.checkpoint_backend = "memory"
    return scratch


def write_record(
    rows: list[RunItem],
    settings: Settings,
    versions: PolicyVersions,
    started_at: datetime,
    sha: str,
    dirty: bool,
    build_id: str | None,
    *,
    run_root: Path = RUNS,
) -> Path:
    dataset = load_registry()["eval_v2"]
    return write_run(
        RunManifest(
            kind=KIND,
            split="dev-test",
            git_sha=sha,
            dirty=dirty,
            config_hash=digest(
                json_text(
                    {
                        "settings": settings.model_dump(mode="json", exclude={"orders"}),
                        "policy_version_spec": versions.model_dump(mode="json"),
                        "requests": REQUESTS,
                    }
                )
            ),
            models=_model_names(settings),
            datasets={dataset.name: DatasetVersion(version=dataset.version, sha256=dataset.sha256)},
            started_at=started_at,
            ended_at=datetime.now(UTC),
            seed=settings.eval.stats.seed,
            cost_usd=None,
            cost_note="real models; cost not tracked by this evaluator",
            command=["make", "eval-time-sensitive-e2e"],
            source={"build_id": build_id, "customer_id": "CUST-TS01"},
        ),
        rows,
        root=run_root,
        suffix=uuid4().hex,
    )


def _cell(rows: list[RunItem], metric: str, alpha: float) -> str:
    count = sum(row.metrics[metric] is True for row in rows)
    interval = wilson_interval(count, len(rows), alpha)
    return f"{count}/{len(rows)} [{interval.low:.0%}, {interval.high:.0%}]"


def write_report(path: Path, output: Path = REPORT) -> None:
    run = read_run(path)
    alpha = get_settings().eval.stats.alpha
    lines = [
        "# Refund path end to end on dated orders",
        "",
        "Generated by `make eval-time-sensitive-e2e` from its run record. Real models.",
        "",
        f"- Run: `{path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path}`",
        f"- Git SHA: `{run.manifest.git_sha}` (dirty: {run.manifest.dirty})",
        f"- Models: {run.manifest.models}",
        f"- Index build: `{run.manifest.source.get('build_id')}`",
        "- Requests per order: "
        + "; ".join(f"`{name}`: {text}" for name, text in REQUESTS.items()),
        "- The notice is expected exactly when the order date selects the historical version.",
        "- Eight dated orders and two requests each: these counts are small; read the rows.",
        "",
        "| Metric | Count [95% Wilson] |",
        "|---|---|",
        *(f"| {metric} | {_cell(run.items, metric, alpha)} |" for metric in METRICS),
        "",
        "| Row | Order date | Decision | Cited | Notice expected / present | Handoff |",
        "|---|---|---|---|---|---|",
    ]
    for row in run.items:
        payload = row.payload
        cited = ", ".join(
            s.split(".")[0] + ("@old" if "@" in s else "") for s in payload["cited_sections"]
        )
        lines.append(
            f"| `{row.id}` | {payload['order_date']} | {payload['decision']} | {cited or '—'} | "
            f"{payload['expected_notice']} / {payload['notice_present']} | "
            f"{row.handoff_reason or '—'} |"
        )
    write_text(output, "\n".join(lines) + "\n")


def main(argv: list[str] | None = None, *, graph_factory: Callable[..., Any] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-from", type=Path)
    args = parser.parse_args(argv)
    if args.report_from:
        write_report(args.report_from)
        return 0
    # Real models need the LLM_* variables, as the other real-model evaluators do.
    load_dotenv(REPO_ROOT / ".env", override=False)
    get_settings.cache_clear()
    base = get_settings()
    versions = load_versions(base.policy_versions)
    items = [item for item in load_items(load_registry()["eval_v2"]) if item.path == "refund"]
    started_at, sha, dirty = datetime.now(UTC), git("rev-parse", "HEAD"), is_dirty()
    with tempfile.TemporaryDirectory(prefix="atlas-ts-e2e-") as folder:
        settings = scratch_settings(base, Path(folder))
        with GraphDeps(settings) as deps:
            graph = (graph_factory or build_graph)(deps)
            rows = collect(graph, items, versions)
            build_id = deps.current_build_id()
    if not any(row.metrics["refund_path"] for row in rows):
        raise RuntimeError("No conversation reached the refund path; check the model settings")
    path = write_record(rows, settings, versions, started_at, sha, dirty, build_id)
    write_report(path)
    sys.stdout.write(f"{path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
