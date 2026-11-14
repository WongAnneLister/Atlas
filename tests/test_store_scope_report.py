from __future__ import annotations

import json
from pathlib import Path

import pytest
from eval import store_scope_report as report
from eval.e2e_records import E2EMetadata, E2ERecord
from eval.schema import EvalItem

from support_agent.config import Settings

SCOPE = Settings().retrieval.store_scope
METADATA = {
    "git_sha": "sha",
    "config_hash": "c",
    "eval_file_hash": "e",
    "corpus_hash": "k",
    "models": {"main": "m"},
    "dataset_versions": {},
    "split": "test",
    "date": "today",
    "customer_id": "CUST-0001",
    "threshold": 0.15,
}


def record(item_id: str, answerable: bool, accepted: bool) -> E2ERecord:
    return E2ERecord(
        item=EvalItem(
            id=item_id,
            group="basic_policy" if answerable else "no_answer",
            split="test",
            question="q",
            gold_sections=["s"] if answerable else [],
            answer_points=["p"] if answerable else [],
            answerable=answerable,
            source="fixture",
            notes=json.dumps({"family": "to_generic"}) if not answerable else "",
        ),
        trace=["answer"] if accepted else ["handoff"],
        answer="a" if accepted else "",
        accepted=accepted,
        latency_full_answer_s=0.1,
    )


def write_run(path: Path, records: list[E2ERecord], metadata: E2EMetadata) -> None:
    path.write_text(
        "\n".join([metadata.model_dump_json(), *[r.model_dump_json() for r in records]]) + "\n"
    )


def test_section_reports_rates_families_and_changed_items(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(report, "REPO_ROOT", tmp_path)
    metadata = E2EMetadata.model_validate(METADATA)
    write_run(tmp_path / "a.jsonl", [record("n1", False, True), record("y1", True, True)], metadata)
    write_run(
        tmp_path / "b.jsonl", [record("n1", False, False), record("y1", True, True)], metadata
    )
    text = "\n".join(
        report.section(report.Pair("Set", Path("a.jsonl"), Path("b.jsonl"), "r"), SCOPE)
    )
    assert "| False accept (no-answer accepted) | 1/1" in text
    assert "| to_generic | 1 | 1 | 0 |" in text
    assert "| same path, filter had nothing to remove | 0 | 1 |" in text


def test_section_rejects_runs_over_different_items(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(report, "REPO_ROOT", tmp_path)
    metadata = E2EMetadata.model_validate(METADATA)
    write_run(tmp_path / "a.jsonl", [record("n1", False, True)], metadata)
    write_run(tmp_path / "b.jsonl", [record("n2", False, True)], metadata)
    with pytest.raises(ValueError, match="different items"):
        report.section(report.Pair("Set", Path("a.jsonl"), Path("b.jsonl"), "r"), SCOPE)
