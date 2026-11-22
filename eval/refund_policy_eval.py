"""Refund policy retrieval: gate outcome of the refund path's policy query on every mock order.

Runs `RefundPath.retrieve_policy` (real retrieval, rerank, store scope and gate) for each
seeded order under both `refund.policy_query` modes. No LLM calls: the decision step is
not run, so this measures whether the refund path can reach a decision, not whether the
decision is right. The query depends only on order facts, so many orders share a query;
each distinct query is retrieved once.
"""

from __future__ import annotations

import argparse
import statistics
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.data.doc_models import digest, json_text, write_text
from support_agent.graph.deps import GraphDeps
from support_agent.graph.intents import Intent
from support_agent.graph.nodes.refund import RefundPath
from support_agent.graph.refund_query import template_key
from support_agent.graph.state import ConversationState
from support_agent.orders.models import Order
from support_agent.orders.service import OrderService
from support_agent.retrieval.index_snapshot import load_build_chunks
from support_agent.retrieval.scope import section_store
from support_agent.retrieval.types import RetrievedChunk

REPORT = Path("eval/reports/refund_policy.md")
MODES: tuple[Literal["order_fields", "store_faq"], ...] = ("order_fields", "store_faq")
MAX_ORDERS_PER_CUSTOMER = 1000
# Tries per distinct query; the SSH-forwarded Milvus connection can drop for a moment.
RETRIEVAL_ATTEMPTS = 3


@dataclass(frozen=True)
class Row:
    mode: str
    order_id: str
    status: str
    key: str
    query: str
    passed: bool
    score: float
    reason: str
    top_store: str
    policy_store_in_top5: bool
    other_store_in_top5: int
    retrieval_error: bool = False


class CachingRetriever:
    """Retrieve each distinct query once; both modes and all orders share the cache."""

    def __init__(self, inner: Any, attempts: int = RETRIEVAL_ATTEMPTS) -> None:
        self.inner = inner
        self.attempts = attempts
        self.cache: dict[tuple[str, int], list[RetrievedChunk]] = {}
        self.failed: set[str] = set()

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        key = (query, top_k)
        if key not in self.cache:
            for attempt in range(1, self.attempts + 1):
                try:
                    self.cache[key] = self.inner.retrieve(query, top_k)
                    break
                except Exception:
                    if attempt == self.attempts:
                        self.failed.add(query)
                        raise
        return [chunk.model_copy(deep=True) for chunk in self.cache[key]]


def all_orders(service: OrderService, n_customers: int) -> list[Order]:
    orders = [
        order
        for customer in service.list_customers(n_customers)
        for order in service.list_recent_orders(customer.customer_id, MAX_ORDERS_PER_CUSTOMER)
    ]
    return sorted(orders, key=lambda order: order.order_id)


def measure(path: RefundPath, order: Order, mode: str, settings: Settings, failed: set[str]) -> Row:
    state = ConversationState(
        customer_id=order.customer_id,
        intent=Intent.REFUND_REQUEST,
        order_context={"order": order.model_dump(mode="json")},
    )
    result = path.retrieve_policy(state)
    gate = result["gate"]
    chunks: list[RetrievedChunk] = result["retrieval"]
    scope = settings.retrieval.store_scope
    stores = [section_store(chunk.section_id, scope) or "none" for chunk in chunks]
    policy = settings.refund.policy_store
    return Row(
        mode=mode,
        order_id=order.order_id,
        status=order.status.value,
        key=template_key(order),
        query=result["refund_policy_query"],
        passed=bool(gate.passed),
        score=float(gate.score),
        reason=str(gate.reason),
        top_store=stores[0] if stores else "empty",
        policy_store_in_top5=policy in stores,
        other_store_in_top5=sum(store not in (policy, "none") for store in stores),
        retrieval_error=result["refund_policy_query"] in failed,
    )


def _rate(part: int, whole: int) -> str:
    return f"{part}/{whole} ({part / whole:.2%})" if whole else "0/0"


def summary_lines(rows: list[Row], policy_store: str) -> list[str]:
    lines = [
        "| Mode | Orders | Distinct queries | Gate passed | Top-1 from policy store "
        "| Other-store chunks in top 5 | Median gate score | Retrieval errors |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for mode in MODES:
        part = [row for row in rows if row.mode == mode]
        if not part:
            continue
        lines.append(
            f"| {mode} | {len(part)} | {len({row.query for row in part})} "
            f"| {_rate(sum(row.passed for row in part), len(part))} "
            f"| {_rate(sum(row.top_store == policy_store for row in part), len(part))} "
            f"| {sum(row.other_store_in_top5 for row in part)} "
            f"| {statistics.median(row.score for row in part):.4f} "
            f"| {sum(row.retrieval_error for row in part)} |"
        )
    return lines


def by_status_lines(rows: list[Row]) -> list[str]:
    lines = [
        "| Order status | " + " | ".join(f"{mode} passed" for mode in MODES) + " |",
        "|---|" + "---:|" * len(MODES),
    ]
    for status in sorted({row.status for row in rows}):
        cells = []
        for mode in MODES:
            part = [row for row in rows if row.mode == mode and row.status == status]
            cells.append(_rate(sum(row.passed for row in part), len(part)))
        lines.append(f"| {status} | " + " | ".join(cells) + " |")
    return lines


def query_lines(rows: list[Row]) -> list[str]:
    lines = [
        "| Question key | Query | Orders | Gate score | Passed | Gate reason | Top-1 store |",
        "|---|---|---:|---:|---|---|---|",
    ]
    part = [row for row in rows if row.mode == "store_faq"]
    for query, count in sorted(Counter(row.query for row in part).items()):
        row = next(r for r in part if r.query == query)
        lines.append(
            f"| {row.key} | {query} | {count} | {row.score:.4f} | {row.passed} "
            f"| {row.reason} | {row.top_store} |"
        )
    return lines


def write_report(
    rows: list[Row], settings: Settings, path: Path, build_id: str | None = None
) -> None:
    variant = settings.model_dump(mode="json")
    variant.pop("refund", None)
    corpus = (
        digest(
            "".join(
                chunk.model_dump_json() + "\n" for chunk in load_build_chunks(settings, build_id)
            )
        )
        if build_id
        else "unresolved"
    )
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    retrieval = settings.retrieval
    lines = [
        "# Refund policy retrieval",
        "",
        "Generated by `make eval-refund-policy`. Do not edit by hand.",
        "",
        f"- Git SHA (base revision): `{sha}`",
        f"- Config hash (without the refund section): `{digest(json_text(variant))}`",
        f"- Corpus hash (local chunks file): `{corpus}`",
        f"- Date (UTC): {datetime.now(UTC).isoformat()}",
        f"- Models: embedding `{retrieval.embedding_model}`, reranker `{retrieval.reranker_model}`"
        f" on `{retrieval.reranker_device}`. No LLM calls.",
        f"- Collection: `{settings.milvus.collection}`; gate threshold {settings.gate.threshold};"
        f" policy store `{settings.refund.policy_store}`.",
        "- Orders: every seeded mock order (all customers). There is no dev/test split here.",
        "- The store_faq questions were written after reading the generic store FAQ questions",
        "  and probing a few fixed queries by hand. They were not tuned on these orders.",
        "",
        "## Definitions",
        "",
        "The gate decides whether the refund path may call the decision model at all.",
        "A failed gate hands off with `low_evidence`; a passed gate allows a decision.",
        '"Policy store" is the store that sells the mock orders (`refund.policy_store`).',
        "Other-store chunks are policy sections of any other store in the top 5.",
        f"A retrieval error (after {RETRIEVAL_ATTEMPTS} tries) fails closed: not passed.",
        "This does not measure decision quality; that needs the decision model and review.",
        "",
        "## Summary",
        "",
        *summary_lines(rows, settings.refund.policy_store),
        "",
        "## Gate passed by order status",
        "",
        *by_status_lines(rows),
        "",
        "## store_faq queries",
        "",
        *query_lines(rows),
        "",
    ]
    write_text(path, "\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args(argv)
    base = get_settings()
    service = OrderService(settings=base.orders)
    orders = all_orders(service, base.orders.n_customers + 1)
    rows: list[Row] = []
    with GraphDeps(base) as deps:
        retriever = CachingRetriever(deps.knowledge_retriever())
        for mode in MODES:
            settings = base.model_copy(deep=True)
            settings.refund.policy_query = mode
            path = RefundPath(GraphDeps(settings, retriever=retriever, order_service=service))
            rows += [measure(path, order, mode, settings, retriever.failed) for order in orders]
        build_id = deps.current_build_id()
    write_report(rows, base, REPO_ROOT / args.report, build_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
