"""Offline checks for the refund policy report (no Milvus, no models)."""

from __future__ import annotations

from datetime import date
from typing import Any

from eval.refund_policy_eval import CachingRetriever, Row, by_status_lines, summary_lines

from support_agent.retrieval.filters import RetrievalFilters


def row(mode: str, order_id: str, passed: bool, top: str, other: int = 0, **kw: Any) -> Row:
    return Row(
        mode=mode,
        order_id=order_id,
        status=kw.get("status", "delivered"),
        key="default",
        query=kw.get("query", f"{mode} query"),
        passed=passed,
        score=0.8 if passed else 0.05,
        reason="passed" if passed else "below_threshold",
        top_store=top,
        policy_store_in_top5=top == "generic",
        other_store_in_top5=other,
    )


def test_summary_counts_pass_store_and_distinct_queries() -> None:
    rows = [
        row("order_fields", "ORD-1", False, "flipkart", other=3, query="a"),
        row("order_fields", "ORD-2", False, "flipkart", other=2, query="b"),
        row("store_faq", "ORD-1", True, "generic"),
        row("store_faq", "ORD-2", True, "generic"),
    ]
    lines = summary_lines(rows, "generic")
    assert lines[2] == "| order_fields | 2 | 2 | 0/2 (0.00%) | 0/2 (0.00%) | 5 | 0.0500 | 0 |"
    assert lines[3] == "| store_faq | 2 | 1 | 2/2 (100.00%) | 2/2 (100.00%) | 0 | 0.8000 | 0 |"


def test_status_breakdown_has_one_row_per_status() -> None:
    rows = [
        row("order_fields", "ORD-1", False, "x", status="paid"),
        row("store_faq", "ORD-1", True, "generic", status="paid"),
        row("order_fields", "ORD-2", True, "x", status="shipped"),
        row("store_faq", "ORD-2", False, "generic", status="shipped"),
    ]
    assert by_status_lines(rows)[2:] == [
        "| paid | 0/1 (0.00%) | 1/1 (100.00%) |",
        "| shipped | 1/1 (100.00%) | 0/1 (0.00%) |",
    ]


def test_cache_retrieves_each_query_once() -> None:
    calls: list[str] = []

    class Inner:
        def retrieve(self, query: str, top_k: int) -> list[Any]:
            calls.append(query)
            return []

    cached = CachingRetriever(Inner())
    cached.retrieve("q", 5)
    cached.retrieve("q", 5)
    assert calls == ["q"]


def test_cache_retrieves_each_date_and_category_independently() -> None:
    calls: list[tuple[date | None, str | None]] = []

    class Inner:
        def supports_filters(self) -> bool:
            return True

        def retrieve(self, query: str, top_k: int, filters=None) -> list[Any]:
            calls.append((filters.as_of, filters.product_category) if filters else (None, None))
            return []

    cached = CachingRetriever(Inner())
    old, new = date(2026, 8, 31), date(2026, 9, 1)
    assert cached.supports_filters()
    cached.retrieve("same query", 5)
    for day, category in [(old, None), (new, None), (old, None), (new, "hair_dryers")]:
        cached.retrieve("same query", 5, RetrievalFilters(as_of=day, product_category=category))
    assert calls == [(None, None), (old, None), (new, None), (new, "hair_dryers")]


def test_cache_retries_and_raises_on_terminal_failure() -> None:
    import pytest

    tries: list[str] = []

    class Flaky:
        def retrieve(self, query: str, top_k: int) -> list[Any]:
            tries.append(query)
            if query == "down" or len(tries) == 1:
                raise ConnectionError("tunnel")
            return []

    cached = CachingRetriever(Flaky(), attempts=2)
    assert cached.retrieve("up", 5) == []
    with pytest.raises(ConnectionError):
        cached.retrieve("down", 5)
    assert tries == ["up", "up", "down", "down"]
