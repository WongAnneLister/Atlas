from pathlib import Path

from eval.context_regression_report import COMPARISONS, GATES, TABLES, gate_lines


def test_gate_lines_list_each_gate_with_its_verdict(tmp_path: Path) -> None:
    for file in GATES.values():
        (tmp_path / file).write_text(
            "# Eval release gate — Passed\n\n| a |\n|---|\n| 1 |\n\n| Category |\n|---|\n",
            encoding="utf-8",
        )
    lines = gate_lines(tmp_path)
    assert lines.count("- Eval release gate — Passed") == len(GATES)
    assert "| Category |" not in lines


def test_every_table_and_comparison_names_a_saved_file() -> None:
    assert all(
        file.startswith("compare-") and file.endswith(".md") for file in COMPARISONS.values()
    )
    assert all(arms for _, arms, _ in TABLES.values())
