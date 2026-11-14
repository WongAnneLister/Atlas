from __future__ import annotations

from pathlib import Path

from eval import store_fr_report as report
from eval.e2e_records import E2EMetadata

from test_store_scope_report import METADATA, SCOPE, record, write_run


def test_report_counts_consistent_losses_and_noise(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(report, "REPO_ROOT", tmp_path)
    (tmp_path / "eval/runs").mkdir(parents=True)
    metadata = E2EMetadata.model_validate(METADATA)
    for config in ("off", "on"):
        for rep in (1, 2):
            records = [
                record("kept", True, True),
                record("lost", True, config == "off"),
                record("flaky", True, rep == 1),
                record("none", False, False),
            ]
            write_run(tmp_path / report.run_path("dev", config, rep), records, metadata)
    text = "\n".join(report.set_section("dev", SCOPE))
    assert "both on runs: 1" in text
    assert "1 outcomes flip between two filter-off runs" in text
    assert "`lost`" in text


def test_missing_runs_are_reported_not_invented(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(report, "REPO_ROOT", tmp_path)
    assert "Not measured" in "\n".join(report.set_section("controls", SCOPE))
    assert Path(report.REPORT).name == "store_false_rejects.md"
