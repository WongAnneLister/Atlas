from __future__ import annotations

from pathlib import Path

import pytest
from eval.compare import compare_runs
from eval.e2e_eval import _record, _write_report
from eval.e2e_records import E2EMetadata, E2ERecord
from eval.judge import export_csv, import_confirmations, judge_record
from eval.metrics import outcome_rates, percentile
from eval.schema import EvalItem
from eval.sweep import (
    GateScore,
    GateScoreMetadata,
    _write_config_threshold,
    rates_for_records,
    select_threshold,
    write_report,
)
from langchain_core.language_models.fake_chat_models import FakeListChatModel


def score(item_id: str, answerable: bool, value: float) -> GateScore:
    return GateScore(
        id=item_id,
        group="basic_policy" if answerable else "no_answer",
        split="dev",
        answerable=answerable,
        score=value,
        signals={"top_score": value},
    )


def test_sweep_selects_lowest_threshold_with_zero_false_accept() -> None:
    records = [score("answerable", True, 0.20), score("no-answer", False, 0.31)]
    assert select_threshold(records) == 0.32
    rates = rates_for_records(records, 0.32)
    assert rates.false_accept == 0
    assert rates.false_reject == 1.0


def test_sweep_midpoint_rule_centres_the_dev_gap() -> None:
    records = [
        score("no-answer", False, 0.10),
        score("answerable-low", True, 0.50),
        score("answerable-high", True, 0.90),
    ]
    assert select_threshold(records, "lowest") == 0.11
    assert select_threshold(records, "midpoint") == 0.30
    assert rates_for_records(records, 0.30).false_reject == 0


def test_sweep_never_passes_a_vetoed_record() -> None:
    vetoed = score("no-answer", False, 0.95).model_copy(update={"vetoed": True})
    records = [vetoed, score("answerable", True, 0.60)]
    assert rates_for_records(records, 0.05).false_accept == 0
    assert select_threshold(records, "lowest") == 0.05
    assert select_threshold(records, "midpoint") == 0.30


def test_sweep_reports_no_threshold_when_no_answer_score_is_maximum() -> None:
    records = [score("answerable", True, 0.50), score("no-answer", False, 1.0)]
    assert select_threshold(records) is None


def test_sweep_report_lists_held_out_false_accepts(tmp_path) -> None:
    metadata = GateScoreMetadata(
        git_sha="fixture",
        config_hash="config",
        eval_file_hash="eval",
        corpus_hash="corpus",
        split="dev",
        date="fixture",
        models={},
        dataset_versions={},
    )
    test = score("held-out-failure", False, 0.6).model_copy(update={"split": "test"})
    path = tmp_path / "sweep.md"
    write_report(
        metadata,
        [score("dev-safe", False, 0.1)],
        0.17,
        metadata.model_copy(update={"split": "test"}),
        [test],
        path,
    )
    assert "held-out-failure" in path.read_text()


def test_sweep_clears_unmeasured_threshold_and_keeps_yaml_comments(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    config_path = config_dir / "default.yaml"
    config_path.write_text(
        "gate:\n  threshold: 0.70 # old value\nother:\n  keep: true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("eval.sweep.REPO_ROOT", tmp_path)
    _write_config_threshold(None, Path("eval/reports/threshold_sweep.md"), "abc123")
    content = config_path.read_text(encoding="utf-8")
    assert "threshold: null # no zero-false-accept threshold" in content
    assert "abc123" in content
    assert "keep: true" in content


def test_rates_require_matching_nonempty_inputs() -> None:
    assert outcome_rates([True, False], [True, False]).pass_rate == 0.5
    with pytest.raises(ValueError):
        outcome_rates([], [])
    with pytest.raises(ValueError):
        outcome_rates([True], [True, False])


def test_percentile_rejects_invalid_latency() -> None:
    assert percentile([1.0, 2.0, 3.0], 95) == 3.0
    with pytest.raises(ValueError):
        percentile([-1.0], 50)


def eval_item(item_id: str) -> EvalItem:
    return EvalItem(
        id=item_id,
        group="basic_policy",
        split="test",
        question="How long is the return window?",
        gold_sections=["returns.policy"],
        answer_points=["thirty days"],
        answerable=True,
        source="fixture",
    )


def e2e_record(item_id: str, accepted: bool, handoff: str | None = None) -> E2ERecord:
    return E2ERecord(
        item=eval_item(item_id),
        trace=["answer"] if accepted else ["handoff"],
        answer="Answer" if accepted else "Please wait",
        handoff_reason=handoff,
        accepted=accepted,
        latency_full_answer_s=0.1,
    )


def test_compare_reports_changed_outcomes() -> None:
    left = {"one": e2e_record("one", False, "low_evidence")}
    right = {"one": e2e_record("one", True)}
    result = compare_runs(left, right)
    assert result["shared_items"] == 1
    assert result["deltas"]["pass_rate"] == 1.0
    assert result["changed"] == [
        {
            "id": "one",
            "accepted_a": False,
            "accepted_b": True,
            "handoff_a": "low_evidence",
            "handoff_b": None,
        }
    ]


def test_e2e_retains_failure_fields_without_inventing_legacy_diagnostics() -> None:
    record = _record(
        eval_item("failed"),
        {
            "classification_failed": True,
            "classification_error_type": "ConnectionError",
            "retrieval_error_type": "TimeoutError",
            "answer_status": "model_error",
            "answer_error_type": "ConnectionError",
        },
        0.1,
        None,
        (None, None),
    )
    assert record.classification_failed is True
    assert record.classification_error_type == "ConnectionError"
    assert record.retrieval_error_type == "TimeoutError"
    assert record.answer_status == "model_error"
    assert record.answer_error_type == "ConnectionError"
    legacy = E2ERecord.model_validate(e2e_record("legacy", False).model_dump())
    assert legacy.classification_failed is None
    assert legacy.answer_status is None


def test_judge_exports_claims_and_imports_human_confirmation(tmp_path) -> None:
    record = e2e_record("one", True)
    record.cited_sources = [
        {
            "section_id": "returns.policy",
            "heading_path": "Returns",
            "text": "Return within 30 days.",
        }
    ]
    model = FakeListChatModel(responses=['{"flagged":true,"claims":["It is free."]}'])
    result = judge_record(model, "Judge prompt", record)
    original = tmp_path / "review.csv"
    export_csv([result], original)
    confirmation = tmp_path / "confirmed.csv"
    confirmation.write_text("item_id,confirmed\none,yes\n", encoding="utf-8")
    imported = import_confirmations(original, confirmation)
    assert imported[0].flagged
    assert imported[0].claims == ["It is free."]
    assert imported[0].confirmed == "yes"


def test_e2e_citation_validity_uses_unique_cited_sections(tmp_path) -> None:
    record = e2e_record("citation", True)
    record.cited_sources = [
        {"section_id": "returns.policy", "heading_path": "Returns", "text": "A"},
        {"section_id": "returns.policy", "heading_path": "Returns", "text": "A"},
    ]
    metadata = E2EMetadata(
        git_sha="abc",
        config_hash="config",
        eval_file_hash="eval",
        corpus_hash="corpus",
        models={"fast": "fast", "main": "main"},
        dataset_versions={},
        split="test",
        date="2026-11-10T00:00:00Z",
        customer_id="CUST-0001",
        threshold=0.5,
    )
    report = tmp_path / "e2e.md"

    _write_report([record], metadata, report)

    assert "| Citation validity | 1.0000 |" in report.read_text(encoding="utf-8")

    record.item = record.item.model_copy(
        update={"id": "accepted-no-answer", "answerable": False, "group": "no_answer"}
    )
    _write_report([record], metadata, report)
    assert "accepted-no-answer" in report.read_text(encoding="utf-8")


def test_e2e_diagnostics_report_keeps_legacy_status_unknown(tmp_path) -> None:
    metadata = E2EMetadata(
        git_sha="fixture",
        config_hash="config",
        eval_file_hash="eval",
        corpus_hash="corpus",
        models={},
        dataset_versions={},
        split="test",
        date="fixture",
        customer_id="fixture",
        threshold=0.17,
    )
    legacy = e2e_record("legacy", False).model_copy(update={"gate": {"passed": False}})
    failed = e2e_record("failed", False).model_copy(
        update={
            "classification_failed": True,
            "classification_error_type": "ConnectionError",
            "answer_status": "not_attempted",
        }
    )
    path = tmp_path / "report.md"
    _write_report([legacy, failed], metadata, path)
    report = path.read_text()
    assert "| Classification call failed | 1 |" in report
    assert "| Diagnostic fields unavailable | 1 |" in report
    assert "| Gate rejected without retrieval error | 0 |" in report
