from __future__ import annotations

from pathlib import Path

from eval import tools_fallback_report as report
from eval.e2e_records import E2EMetadata

from test_store_scope_report import METADATA, record, write_run


def fallback(item_id: str, answerable: bool, accepted: bool):
    entry = record(item_id, answerable, accepted)
    return entry.model_copy(update={"trace": ["tools", "tools_fallback", *entry.trace]})


def test_section_counts_gains_losses_and_unsafe_fallbacks(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(report, "REPO_ROOT", tmp_path)
    metadata = E2EMetadata.model_validate(METADATA)
    before = [record("gain", True, False), record("keep", True, True), record("na", False, False)]
    after = [fallback("gain", True, True), record("keep", True, True), fallback("na", False, True)]
    for name, rows in (("b1", before), ("b2", before), ("a1", after), ("a2", after)):
        write_run(tmp_path / f"{name}.jsonl", rows, metadata)
    comparison = report.Comparison(
        "Set", (Path("b1.jsonl"), Path("b2.jsonl")), (Path("a1.jsonl"), Path("a2.jsonl"))
    )
    text = "\n".join(report.section(comparison, set()))
    assert "accepted in every after run: 1 (via fallback: 1)" in text
    assert "rejected in every after run: 0 (via fallback: 0)" in text
    assert "paired before run): 1, 1" in text
    assert "No-answer items accepted through the fallback: 2" in text
    assert "Fallback taken (all after runs pooled): 4" in text
