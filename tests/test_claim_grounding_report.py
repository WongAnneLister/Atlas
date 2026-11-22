import json
from pathlib import Path

from eval.claim_grounding_report import _kind, gate_lines, removal_lines


def test_missed_claim_kinds_follow_the_drafting_rule():
    assert _kind("Yes. Contact support.") == "leading yes/no not stated in the source"
    assert _kind("The sources do not list brands.") == "statement about the sources"
    assert _kind("Returns take 30 days.") == "other"


def test_removal_table_lists_reasons_and_handoffs():
    lines = removal_lines(
        {
            "removals": {
                "v1-test-on": {"claims": 3, "removed": 1, "reasons": {"x": 1}, "low_grounding": 0}
            }
        }
    )
    assert "| v1-test-on | 3 | 1 | x 1 | 0 |" in lines


def test_gate_lines_keep_table_separators(tmp_path: Path):
    (tmp_path / "gate.md").write_text(
        "# Eval release gate — Passed\n\n| a |\n|---|\n| 1 |\n\n## Red-team\n\n| b |\n|---|\n",
        encoding="utf-8",
    )
    lines = gate_lines(tmp_path)
    assert "- Eval release gate — Passed" in lines
    assert lines.count("|---|") == 2
    assert json.dumps(lines)
