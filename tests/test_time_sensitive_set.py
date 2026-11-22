from collections import Counter
from datetime import date

import pytest
from eval.build_time_sensitive import build_items, extend_dataset
from eval.schema import GROUPS, EvalItem, TimeSensitiveItem

from support_agent.config import get_settings
from support_agent.graph.refund_query import policy_query
from support_agent.orders.fixtures import time_sensitive_fixtures

V1_ROW = (
    b'{"id":"frozen","group":"basic_policy","split":"test","question":"How long?",'
    b'"gold_sections":["returns"],"answer_points":["30 days"],"answerable":true,'
    b'"source":"fixture","reviewed":false,"notes":""}\n'
)


def test_v1_record_dump_and_dataset_prefix_stay_identical():
    assert EvalItem.model_validate_json(V1_ROW).model_dump_json().encode() + b"\n" == V1_ROW
    assert "time_sensitive" not in GROUPS
    items = build_items(get_settings())
    data = extend_dataset(V1_ROW, items)
    assert data.startswith(V1_ROW)
    assert [TimeSensitiveItem.model_validate_json(row) for row in data.splitlines()[1:]] == items


def test_generated_labels_follow_trusted_dates_on_both_splits():
    settings = get_settings()
    items = build_items(settings)
    assert Counter((item.split, item.path) for item in items) == {
        ("dev", "knowledge"): 20,
        ("test", "knowledge"): 20,
        ("dev", "refund"): 4,
        ("test", "refund"): 4,
    }
    assert len({item.id for item in items}) == len({item.question for item in items}) == 48
    for item in items:
        if item.path == "knowledge":
            assert item.as_of == settings.orders.today
            assert item.customer_id is item.order_id is None
        else:
            assert item.customer_id == "CUST-TS01"
            assert item.version_of.startswith("returns.")
        old = item.as_of < date(2026, 9, 1)
        assert item.gold_sections == [f"{item.version_of}@2026-01-01" if old else item.version_of]
        if item.version_of.startswith("returns."):
            assert item.answer_points == (["90 days"] if old else ["30 days"])
        else:
            assert item.answer_points == (["14 days"] if old else ["7 days"])
        assert item.source == "synthetic_template"
        assert not item.reviewed
    for split in ("dev", "test"):
        claimed = [
            item
            for item in items
            if item.split == split and item.path == "knowledge" and "August" in item.question
        ]
        assert len(claimed) == 4
        assert all(item.gold_sections == [item.version_of] for item in claimed)


def test_refund_cases_use_one_order_per_date_and_never_share_dates_between_splits():
    items = [item for item in build_items(get_settings()) if item.path == "refund"]
    assert len({item.order_id for item in items}) == len({item.as_of for item in items}) == 8
    assert {
        split: sorted(item.as_of.isoformat() for item in items if item.split == split)
        for split in ("dev", "test")
    } == {
        "dev": ["2026-08-20", "2026-08-31", "2026-09-01", "2026-10-15"],
        "test": ["2026-07-25", "2026-08-30", "2026-09-02", "2026-10-25"],
    }
    orders, _ = time_sensitive_fixtures(get_settings().orders)
    assert {item.order_id: item.as_of for item in items} == {
        order.order_id: order.order_date for order in orders
    }
    assert {policy_query(order, "return_exchange", get_settings()) for order in orders} == {
        f"{get_settings().refund.store_label}: What is your return policy? "
        "Can I return a product for a refund?"
    }


def test_refund_record_requires_both_order_and_customer_ids():
    refund = next(item for item in build_items(get_settings()) if item.path == "refund")
    with pytest.raises(ValueError, match="requires order_id and customer_id"):
        TimeSensitiveItem.model_validate(refund.model_dump(exclude={"customer_id"}))
