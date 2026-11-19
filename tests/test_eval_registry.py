from pathlib import Path

import pytest
from eval.registry import bump, inspect_dataset, validate


def test_registry_hash_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "questions.jsonl"
    path.write_text('{"id":"a","split":"dev","reviewed":false}\n')
    entry = inspect_dataset(path, name="example", version="v1", changelog=["Freeze"], root=tmp_path)
    assert validate({"example": entry}, root=tmp_path)[1] == 0
    path.write_text('{"id":"b","split":"dev","reviewed":false}\n')
    messages, status = validate({"example": entry}, root=tmp_path)
    assert status == 1
    assert "bump the version and add a changelog line" in messages[0]
    with pytest.raises(ValueError, match="version"):
        bump(entry, "v1", "Replacement", root=tmp_path)
    updated = bump(entry, "v2", "Replacement", root=tmp_path)
    assert updated.changelog == ["Freeze", "Replacement"]
    assert validate({"example": updated}, root=tmp_path)[1] == 0


def test_registry_missing_local_dataset(tmp_path: Path) -> None:
    path = tmp_path / "questions.jsonl"
    path.write_text('{"id":"a","split":"dev","reviewed":false}\n')
    entry = inspect_dataset(path, name="example", version="v1", changelog=["Freeze"], root=tmp_path)
    path.unlink()
    messages, status = validate({"example": entry}, root=tmp_path)
    assert status == 0
    assert "SKIP (local only)" in messages[0]
    assert validate({"example": entry}, root=tmp_path, require_present=True)[1] == 1
