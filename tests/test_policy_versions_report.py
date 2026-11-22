import json
from pathlib import Path

from eval.policy_versions_report import _cell, _section, holdout_lines, index_lines
from eval.run_record import MetricSummary


def summary(count: int | None, n: int, point: float) -> MetricSummary:
    return MetricSummary.model_validate(
        {"interval": {"point": point, "low": point, "high": point}, "n": n, "count": count}
    )


def test_counts_use_wilson_and_other_metrics_keep_their_interval() -> None:
    assert _cell(summary(0, 24, 0.0)) == "0/24 [0%, 14%]"
    assert _cell(summary(None, 160, 0.99)) == "0.9900 [0.9900, 0.9900]"
    assert _cell(None) == "—"


def test_section_returns_only_table_rows_of_that_heading() -> None:
    text = "# T\n\n## A\n\n| x |\n|---|\n| 1 |\ntext\n## B\n\n| y |\n"
    assert _section(text, "## A") == ["| x |", "|---|", "| 1 |"]


def test_index_and_holdout_lines_read_saved_outputs(tmp_path: Path) -> None:
    evidence = tmp_path
    (evidence / "index-plan.json").write_text(
        json.dumps(
            {
                "mode": "full",
                "added": ["a@2026-01-01"],
                "changed": ["b"],
                "deleted": [],
                "unchanged": [],
            }
        ),
        encoding="utf-8",
    )
    (evidence / "index-build.json").write_text(
        json.dumps(
            {
                "build_id": "x",
                "mode": "full",
                "chunk_count": 3,
                "embedded_chunks": 3,
                "elapsed_s": 1.0,
            }
        ),
        encoding="utf-8",
    )
    (evidence / "index-status.before.json").write_text(
        json.dumps({"alias": "live", "drift": False}), encoding="utf-8"
    )
    (evidence / "index-release.md").write_text(
        "# Index release — Release\n\n- hit_at_5: 2/2\n- other: ignored\n", encoding="utf-8"
    )
    (evidence / "holdout-dates.json").write_text(
        json.dumps({"orders": 2, "first": "2026-08-01", "last": "2026-10-01", "changed": []}),
        encoding="utf-8",
    )
    lines = index_lines(evidence)
    assert "  - Decision: Release" in lines
    assert "  - hit_at_5: 2/2" in lines and not any("ignored" in line for line in lines)
    assert any("1 added, 1 changed" in line for line in lines)
    assert holdout_lines(evidence)[0].endswith("order date: 0.")
