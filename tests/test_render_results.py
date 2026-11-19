"""README results block: generated from reports, idempotent, and the only place for metrics."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

import render_results as rr

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures" / "results"
PERCENT = re.compile(r"\d+(?:\.\d+)?\s*%")


def _readme(tmp_path: Path) -> Path:
    path = tmp_path / "README.md"
    path.write_text(f"# Title\n\nIntro.\n\n{rr.START}\nold\n{rr.END}\n\nOutro.\n", encoding="utf-8")
    return path


def test_fixture_reports_render_the_expected_block(tmp_path: Path) -> None:
    readme = _readme(tmp_path)
    rr.main(["--reports", str(FIXTURES), "--readme", str(readme)])

    expected = (FIXTURES / "expected_block.md").read_text(encoding="utf-8").rstrip("\n")
    text = readme.read_text(encoding="utf-8")
    assert text == f"# Title\n\nIntro.\n\n{expected}\n\nOutro.\n"
    # The shipped mode's overall test row is used, not a group row or the dev table.
    assert "| Hybrid + rerank (shipped) | 0.9500 | 0.9000 | 5.0000 |" in text
    assert "$0.00080 (800 tokens, 1.20 LLM calls, mean)" in text


def test_rendering_twice_changes_nothing(tmp_path: Path) -> None:
    readme = _readme(tmp_path)
    rr.main(["--reports", str(FIXTURES), "--readme", str(readme)])
    first = readme.read_text(encoding="utf-8")
    rr.main(["--reports", str(FIXTURES), "--readme", str(readme)])
    assert readme.read_text(encoding="utf-8") == first


def test_unpriced_models_say_price_not_set(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    shutil.copytree(FIXTURES, reports)
    e2e = reports / rr.E2E
    e2e.write_text(
        re.sub(r"\$0\.\d+", "price not set", e2e.read_text(encoding="utf-8")), encoding="utf-8"
    )
    block = rr.render_block(reports)
    assert "| Cost per conversation | price not set (800 tokens, 1.20 LLM calls, mean) |" in block


def test_missing_report_or_marker_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(rr.ReportError, match="missing report"):
        rr.render_block(tmp_path)
    with pytest.raises(rr.ReportError, match="marker"):
        rr.replace_block("no markers here", "block")


def test_readme_has_no_percentage_outside_the_generated_block() -> None:
    text = (REPO / "README.md").read_text(encoding="utf-8")
    head, rest = text.split(rr.START)
    _, tail = rest.split(rr.END)
    outside = PERCENT.findall(head + tail)
    assert outside == [], f"metrics belong in the generated block only: {outside}"


def test_readme_block_matches_the_committed_reports() -> None:
    text = (REPO / "README.md").read_text(encoding="utf-8")
    assert rr.render_block(REPO / "eval" / "reports") in text, "run `make results`"


def test_results_confidence_block_matches_saved_reports() -> None:
    text = (REPO / "docs" / "RESULTS.md").read_text(encoding="utf-8")
    block = rr.render_stats_block(REPO / "eval" / "reports")
    assert block in text, "run `make results`"
    assert "Wilson" in block
    assert "kappa:" in block
