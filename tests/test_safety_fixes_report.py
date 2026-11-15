from __future__ import annotations

from pathlib import Path

from eval import safety_fixes_report as report
from eval.e2e_records import E2EMetadata

from test_store_scope_report import METADATA, record, write_run


def test_event_lines_count_each_fix_by_outcome(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(report, "REPO_ROOT", tmp_path)
    metadata = E2EMetadata.model_validate(METADATA)
    grounded = record("a", False, False)
    grounded = grounded.model_copy(update={"trace": ["tools", "ungrounded:2", "tools_fallback"]})
    absent = record("b", False, False).model_copy(update={"answer_status": "implied_by_absence"})
    plain = record("c", True, True)
    write_run(tmp_path / "after.jsonl", [grounded, absent, plain], metadata)
    comparison = report.Comparison("Set", (Path("before.jsonl"),), (Path("after.jsonl"),))
    text = "\n".join(report.event_lines(comparison))
    assert "order answer ungrounded (no-answer, finally handed off): 1" in text
    assert "answer only implied by absence (no-answer, finally handed off): 1" in text


def test_event_lines_skip_missing_runs(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(report, "REPO_ROOT", tmp_path)
    comparison = report.Comparison("Set", (Path("x.jsonl"),), (Path("y.jsonl"),))
    assert report.event_lines(comparison) == []


def test_fixed_lines_name_the_fix_or_say_none_acted(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(report, "REPO_ROOT", tmp_path)
    metadata = E2EMetadata.model_validate(METADATA)
    write_run(
        tmp_path / "before.jsonl",
        [record("a", False, True), record("b", False, True), record("c", False, True)],
        metadata,
    )
    absent = record("a", False, False).model_copy(update={"answer_status": "implied_by_absence"})
    other = record("b", False, False).model_copy(update={"handoff_reason": "low_evidence"})
    still = record("c", False, True)
    write_run(tmp_path / "after.jsonl", [absent, other, still], metadata)
    comparison = report.Comparison("Set", (Path("before.jsonl"),), (Path("after.jsonl"),))
    text = "\n".join(report.fixed_lines(comparison))
    assert "`a`: answer only implied by absence" in text
    assert "`b`: no fix acted (low_evidence)" in text
    assert "`c`" not in text


def test_grounding_outcomes_count_errors_misses_and_passes(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(report, "REPO_ROOT", tmp_path)
    metadata = E2EMetadata.model_validate(METADATA)
    error = record("a", True, False).model_copy(
        update={"trace": ["tools", "grounding_error", "tools_fallback", "handoff"]}
    )
    missing = record("b", True, False).model_copy(
        update={"trace": ["tools", "ungrounded:1", "tools_fallback", "handoff"]}
    )
    passed = record("c", True, True).model_copy(update={"trace": ["tools"]})
    knowledge = record("d", True, True)
    write_run(tmp_path / "after.jsonl", [error, missing, passed, knowledge], metadata)
    comparison = report.Comparison("Set", (Path("before.jsonl"),), (Path("after.jsonl"),))
    text = "\n".join(report.grounding_outcomes([comparison]))
    assert "reached the check, all after runs: 3." in text
    assert "- check error (fails closed): 1" in text
    assert "- claims without a quote: 1" in text
    assert "- passed: 1" in text
