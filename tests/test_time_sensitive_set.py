from collections import Counter
from datetime import date

import pytest
from eval.build_time_sensitive import build_items, extend_dataset
from eval.schema import GROUPS, EvalItem, TimeSensitiveItem

from support_agent.config import get_settings

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
        ("dev", "knowledge"): 8,
        ("test", "knowledge"): 8,
        ("dev", "refund"): 16,
        ("test", "refund"): 16,
    }
    assert len({item.id for item in items}) == len({item.question for item in items}) == 48
    for item in items:
        if item.path == "knowledge":
            assert item.as_of == settings.orders.today
            assert item.customer_id is item.order_id is None
        else:
            assert item.customer_id == "CUST-TS01"
            assert (
                item.order_id
                == {
                    date(2026, 8, 20): "ORD-999996",
                    date(2026, 8, 31): "ORD-999997",
                    date(2026, 9, 1): "ORD-999998",
                    date(2026, 10, 15): "ORD-999999",
                }[item.as_of]
            )
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


def test_refund_record_requires_both_order_and_customer_ids():
    refund = next(item for item in build_items(get_settings()) if item.path == "refund")
    with pytest.raises(ValueError, match="requires order_id and customer_id"):
        TimeSensitiveItem.model_validate(refund.model_dump(exclude={"customer_id"}))
