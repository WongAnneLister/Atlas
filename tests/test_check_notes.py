from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import check_notes

FIXTURES = Path(__file__).parent / "fixtures" / "notes"
REPORT = "# Retrieval\n\n| config | recall@5 |\n|---|---|\n| hybrid | 0.71 |\n| +rerank | 0.84 |\n"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "docs" / "notes").mkdir(parents=True)
    (tmp_path / "eval" / "reports").mkdir(parents=True)
    (tmp_path / "eval" / "reports" / "retrieval.md").write_text(REPORT, encoding="utf-8")
    return tmp_path


def _place(root: Path, fixture: str, name: str) -> Path:
    target = root / "docs" / "notes" / name
    shutil.copy(FIXTURES / fixture, target)
    return target


def _messages(root: Path, note: Path) -> list[str]:
    return [p.message for p in check_notes.check_note(note, root)]


def test_good_note_with_source_passes(root: Path) -> None:
    note = _place(root, "good_source.md", "08-rerank.md")
    assert _messages(root, note) == []


def test_good_note_without_number_passes(root: Path) -> None:
    note = _place(root, "good_no_number.md", "01-scaffold.md")
    assert _messages(root, note) == []


def test_bad_style_is_reported(root: Path) -> None:
    messages = _messages(root, _place(root, "bad_style.md", "02-bad.md"))
    joined = "\n".join(messages)
    assert "banned word: 'robust'" in joined
    assert "banned word: 'seamless'" in joined
    assert "over 15 words" in joined and "I built a robust" in joined
    assert "'Why' has 1 sentences" in joined
    assert "'A' has 1 sentences" in joined
    assert "but has numbers ['12']" in joined


def test_number_missing_from_source_is_reported(root: Path) -> None:
    messages = _messages(root, _place(root, "bad_number.md", "03-bad.md"))
    assert messages == ["number '0.99' not found in retrieval.md"]


def test_missing_source_file_is_reported(root: Path) -> None:
    (root / "eval" / "reports" / "retrieval.md").unlink()
    messages = _messages(root, _place(root, "good_source.md", "08-rerank.md"))
    assert any("source file not found" in m for m in messages)


def test_wrong_heading_order_is_reported(root: Path) -> None:
    note = _place(root, "good_no_number.md", "01-scaffold.md")
    text = note.read_text(encoding="utf-8").replace("**Why**", "**Reason**")
    note.write_text(text, encoding="utf-8")
    assert "headings must be" in _messages(root, note)[0]


def test_done_commit_without_note_fails(root: Path) -> None:
    progress = "| # | Commit | Status | Notes |\n|---|---|---|---|\n| 01 | Scaffold | done | |\n"
    (root / "docs" / "PROGRESS.md").write_text(progress, encoding="utf-8")
    assert [p.message for p in check_notes.check_all(root)] == ["commit 01 is done but has no note"]
    _place(root, "good_no_number.md", "01-scaffold.md")
    assert check_notes.check_all(root) == []


def test_template_is_ignored_and_build_concatenates(root: Path) -> None:
    shutil.copy(FIXTURES / "bad_style.md", root / "docs" / "notes" / "TEMPLATE.md")
    _place(root, "good_source.md", "08-rerank.md")
    _place(root, "good_no_number.md", "01-scaffold.md")
    assert check_notes.check_all(root) == []
    text = check_notes.build(root).read_text(encoding="utf-8")
    assert text.index("# 01 — Scaffold") < text.index("# 08 — Rerank")
    assert "Bad style" not in text


def test_main_exit_codes(root: Path) -> None:
    _place(root, "good_no_number.md", "01-scaffold.md")
    assert check_notes.main(["--root", str(root)]) == 0
    _place(root, "bad_number.md", "03-bad.md")
    assert check_notes.main(["--root", str(root)]) == 1
