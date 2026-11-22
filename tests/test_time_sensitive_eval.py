from datetime import date
from pathlib import Path

import pytest
from eval.build_time_sensitive import build_items
from eval.common import set_filter_mode
from eval.run_record import read_run
from eval.time_sensitive_eval import collect_run, write_report

from support_agent.config import get_settings
from support_agent.data.policy_versions import load_versions
from support_agent.graph.deps import GraphDeps
from support_agent.orders.fixtures import time_sensitive_fixtures
from support_agent.orders.models import Order
from support_agent.retrieval.filters import RetrievalFilters
from support_agent.retrieval.types import RetrievedChunk


def chunk(section_id: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=section_id,
        doc_id="returns",
        section_id=section_id,
        title="Generic store",
        heading_path="Returns",
        text="The generic store return policy allows a full refund.",
        n_tokens=10,
        scores={"rerank": 10.0},
    )


@pytest.mark.parametrize("mode", ["off", "date", "date_category"])
def test_evaluator_writes_paired_metrics_for_both_paths(tmp_path: Path, mode: str) -> None:
    settings = get_settings().model_copy(deep=True)
    set_filter_mode(settings, mode)
    settings.retrieval.filters.category_terms["hair_dryers"].append("return window")
    versions = load_versions(settings.policy_versions)
    cases = [
        item
        for item in build_items(settings)
        if item.split == "dev" and item.version_of.startswith("returns.")
    ]
    knowledge = next(item for item in cases if "August" in item.question)
    refund = next(item for item in cases if item.as_of == date(2026, 8, 31))
    old_id = refund.gold_sections[0]
    current_id = knowledge.gold_sections[0]
    order = next(
        order
        for order in time_sensitive_fixtures(settings.orders)[0]
        if order.order_id == refund.order_id
    )
    calls: list[tuple[str, RetrievalFilters | None]] = []

    class Retriever:
        def supports_filters(self) -> bool:
            return True

        def retrieve(
            self, query: str, top_k: int, filters: RetrievalFilters | None = None
        ) -> list[RetrievedChunk]:
            calls.append((query, filters))
            if query == knowledge.question:
                return [chunk(current_id)]
            # Both versions can count at the same time.
            return [chunk(current_id), chunk(old_id)] if filters is None else [chunk(old_id)]

    class OrderService:
        def get_order(self, order_id: str, customer_id: str) -> Order:
            assert (order_id, customer_id) == (order.order_id, order.customer_id)
            return order

    with GraphDeps(settings, retriever=Retriever()) as deps:
        path = collect_run(deps, OrderService(), [knowledge, refund], versions, run_root=tmp_path)

    run = read_run(path)
    assert run.manifest.split == "dev"
    assert run.manifest.datasets["eval_v2"].version == "v2"
    assert run.manifest.source["filters"] == mode
    assert calls[0][0] == knowledge.question
    assert calls[1][0] != refund.question
    applied = mode != "off"
    category = "hair_dryers" if mode == "date_category" else None
    assert calls[0][1] == (
        RetrievalFilters(as_of=settings.orders.today, product_category=category)
        if applied
        else None
    )
    assert calls[1][1] == (RetrievalFilters(as_of=order.order_date) if applied else None)
    assert [row.payload["filters"] for row in run.items] == [
        filters.model_dump(mode="json") if filters else None for _, filters in calls
    ]
    assert run.items[0].metrics == {
        "version_hit_at_5": True,
        "wrong_version_at_5": False,
        "gate_pass": True,
        "filters_applied": applied,
    }
    assert run.items[1].metrics == {
        "version_hit_at_5": True,
        "wrong_version_at_5": not applied,
        "gate_pass": True,
        "filters_applied": applied,
    }
    output = tmp_path / "report.md"
    write_report([path], output)
    report = output.read_text()
    assert "| dev | all | 2 | 2/2" in report
    assert "| dev | knowledge | 1 | 1/1" in report
    assert "| dev | refund | 1 | 1/1" in report
    assert "[34.24%, 100.00%]" in report
    assert "Each refund row represents a distinct order date" in report
    assert "policy version selection depends only on the stored order date" in report
