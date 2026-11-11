"""A new safety path must never resume old rows as if it measured the same code."""

import pytest
from eval.e2e_records import E2EMetadata, E2ERecord, load_cached_run

from test_eval_tools import eval_item


def meta(**changes):
    return E2EMetadata(
        git_sha="base",
        config_hash="config",
        eval_file_hash="items",
        corpus_hash="corpus",
        models={"main": "fixture"},
        dataset_versions={},
        split="test",
        date="original",
        customer_id="fixture",
        threshold=0.17,
        code_hash=changes.get("code_hash", "old"),
    )


def test_resume_preserves_original_date_and_rejects_changed_code_or_labels(tmp_path):
    item = eval_item("one")
    path = tmp_path / "run.jsonl"
    row = E2ERecord(item=item, latency_full_answer_s=1)
    path.write_text(meta().model_dump_json() + "\n" + row.model_dump_json() + "\n")
    saved, records = load_cached_run(path, meta().model_copy(update={"date": "later"}), [item])
    assert saved.date == "original"
    assert list(records) == ["one"]
    with pytest.raises(ValueError, match="code_hash"):
        load_cached_run(path, meta(code_hash="new"), [item])
    with pytest.raises(ValueError, match="items"):
        load_cached_run(path, meta(), [item.model_copy(update={"question": "altered"})])
    path.write_text(meta().model_dump_json() + "\n" + (row.model_dump_json() + "\n") * 2)
    with pytest.raises(ValueError, match="duplicate"):
        load_cached_run(path, meta(), [item])
