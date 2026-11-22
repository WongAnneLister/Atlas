import json
from pathlib import Path

from eval.query_planning_report import _section, save_summary, summary_lines


def _run(root: Path, name: str, rows: list[dict]) -> None:
    (root / name).mkdir(parents=True)
    lines = [json.dumps({"id": str(i), "payload": row}) for i, row in enumerate(rows)]
    (root / name / "items.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_section_stops_at_the_next_heading() -> None:
    text = "# T\n\n## Metric deltas (B minus A)\n\n| a |\n|---|\n| 1 |\n\n### Next\n\n| b |\n"
    assert _section(text, "## Metric deltas (B minus A)") == ["| a |", "|---|", "| 1 |"]


def test_summary_counts_planner_reach_misses_and_discarded_runs(tmp_path: Path) -> None:
    evidence, root = tmp_path / "evidence", tmp_path / "runs"
    evidence.mkdir()
    (evidence / "runs.json").write_text(json.dumps({"mp-test-pp": "mp"}), encoding="utf-8")
    split = {"trace": ["plan", "classify"], "route_source": "parts", "llm_calls": 3}
    missed = {
        "trace": ["classify"],
        "route_source": "whole",
        "llm_calls": 2,
        "item": {"question": "Where is it, and also For Flipkart: who pays?"},
    }
    _run(root, "mp", [{**split, "item": {"question": "A? B?"}}, missed])
    _run(root, "gone", [{"handoff_reason": "dependency_unavailable"}, {"handoff_reason": None}])
    rows = [json.loads(line) for line in (root / "gone/items.jsonl").read_text().splitlines()]
    (root / "gone/items.jsonl").write_text(
        "\n".join(json.dumps(row["payload"]) for row in rows) + "\n", encoding="utf-8"
    )
    save_summary(evidence, root, {"remote": root / "gone"}, None)
    data = json.loads((evidence / "summary.json").read_text(encoding="utf-8"))
    assert data["reach"]["mp-test-pp"] == {"n": 2, "planner": 1, "parts": 1, "whole": 1}
    assert data["precheck_miss"]["mp-test-pp"] == {"n": 2, "missed": 1, "for_store": 1}
    assert data["discarded"]["remote"] == {"n": 2, "dependency_unavailable": 1}
    lines = summary_lines(evidence)
    assert "| mp-test-pp | 1/2 | 1/2 | 1/2 |" in lines
    assert any("1/2 handed off as `dependency_unavailable`" in line for line in lines)
