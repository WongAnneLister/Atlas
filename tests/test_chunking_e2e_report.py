from __future__ import annotations

from pathlib import Path

from eval import chunking_e2e_report as report
from eval.e2e_records import E2EMetadata

from test_store_scope_report import METADATA, record, write_run


def test_section_reports_consistent_changes_noise_and_wrong_accepts(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(report, "REPO_ROOT", tmp_path)
    metadata = E2EMetadata.model_validate(METADATA)
    before = [record("gain", True, False), record("lost", True, True), record("na", False, False)]
    after = [record("gain", True, True), record("lost", True, False), record("na", False, True)]
    for name, rows in (("b1", before), ("b2", before), ("a1", after), ("a2", after)):
        write_run(tmp_path / f"{name}.jsonl", rows, metadata)
    comparison = report.Comparison(
        "Set", (Path("b1.jsonl"), Path("b2.jsonl")), (Path("a1.jsonl"), Path("a2.jsonl"))
    )
    text = "\n".join(report.section(comparison, set()))
    assert "accepted in every after run: 1" in text
    assert "rejected in every after run: 1" in text
    assert "lost `lost`" in text
    assert "Noise floor (before): 0 outcomes" in text
    assert "No-answer items accepted in an after run: 1" in text


def test_section_skips_route_ok_items_and_missing_runs(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(report, "REPO_ROOT", tmp_path)
    missing = report.Comparison("Gone", (Path("x.jsonl"),), (Path("y.jsonl"),))
    assert "Not measured" in "\n".join(report.section(missing, set()))
    metadata = E2EMetadata.model_validate(METADATA)
    rows = [record("a", True, True), record("b", True, False)]
    write_run(tmp_path / "b.jsonl", rows, metadata)
    write_run(tmp_path / "a.jsonl", rows, metadata)
    comparison = report.Comparison("Set", (Path("b.jsonl"),), (Path("a.jsonl"),))
    text = "\n".join(report.section(comparison, {"b"}))
    assert "left out: 1" in text
    assert "0/1" in text
