from datetime import UTC, date, datetime
from pathlib import Path

from eval.schema import TimeSensitiveItem
from eval.time_sensitive_e2e import (
    NOTICE_PREFIX,
    claimed_month,
    collect,
    score,
    write_record,
    write_report,
)

from support_agent.config import get_settings
from support_agent.data.policy_versions import load_versions
from support_agent.retrieval.filters import RetrievalFilters


def refund_item(order_id: str, order_date: date) -> TimeSensitiveItem:
    settings = get_settings()
    entry = next(
        e
        for e in load_versions(settings.policy_versions).entries
        if e.base_section_id.startswith("returns.")
    )
    return TimeSensitiveItem(
        id=f"ts-test-returns-refund-{order_id}",
        split="test",
        path="refund",
        question=f"What is the return window for Generic store order {order_id}?",
        as_of=order_date,
        version_of=entry.base_section_id,
        order_id=order_id,
        customer_id="CUST-TS01",
        gold_sections=[entry.section_at(order_date)],
        answer_points=["90 days" if order_date < entry.effective_from else "30 days"],
        answerable=True,
        source="synthetic_template",
    )


def result_for(item: TimeSensitiveItem, *, cite: str, notice: bool, as_of: date) -> dict:
    return {
        "trace": ["classify", "refund_load", "refund_retrieve", "refund_decide"],
        "filters": RetrievalFilters(as_of=as_of),
        "filters_applied": True,
        "citations": [{"n": 1, "section_id": cite}],
        "answer": (f"{NOTICE_PREFIX} {item.as_of}. " if notice else "") + "Approved [1].",
        "refund_decision": {"eligible": "yes"},
    }


def test_claimed_month_is_on_the_other_side_of_the_change() -> None:
    change = date(2026, 9, 1)
    assert claimed_month(date(2026, 8, 31), change) == "October"
    assert claimed_month(date(2026, 9, 1), change) == "August"


def test_score_checks_order_date_version_and_notice() -> None:
    versions = load_versions(get_settings().policy_versions)
    old = refund_item("ORD-999996", date(2026, 8, 20))
    good = score(
        old,
        "plain",
        result_for(old, cite=old.gold_sections[0], notice=True, as_of=old.as_of),
        versions,
    )
    assert good.metrics == {
        "refund_path": True,
        "filter_uses_order_date": True,
        "cites_gold_version": True,
        "cites_wrong_version": False,
        "notice_correct": True,
    }
    current = old.version_of
    bad = score(
        old,
        "claimed_date",
        result_for(old, cite=current, notice=False, as_of=date(2026, 10, 1)),
        versions,
    )
    assert bad.metrics["filter_uses_order_date"] is False
    assert bad.metrics["cites_gold_version"] is False
    assert bad.metrics["cites_wrong_version"] is True
    assert bad.metrics["notice_correct"] is False


def test_collect_sends_two_requests_per_order_and_writes_a_report(tmp_path: Path) -> None:
    settings = get_settings()
    versions = load_versions(settings.policy_versions)
    item = refund_item("ORD-999998", date(2026, 9, 1))
    questions: list[str] = []

    class Graph:
        def invoke(self, value, config):
            questions.append(value["messages"][0].content)
            return result_for(item, cite=item.gold_sections[0], notice=False, as_of=item.as_of)

    rows = collect(Graph(), [item], versions)
    assert [row.id.rsplit(":", 1)[1] for row in rows] == ["plain", "claimed_date"]
    assert "ORD-999998" in questions[0] and "August" in questions[1]
    assert all(row.metrics["notice_correct"] for row in rows)
    path = write_record(
        rows, settings, versions, datetime.now(UTC), "a" * 40, False, "build", run_root=tmp_path
    )
    report = tmp_path / "report.md"
    write_report(path, report)
    text = report.read_text(encoding="utf-8")
    assert "notice_correct | 2/2" in text and "ORD-999998" in text
