"""Summaries must retain every frozen item, including failed or rejected cases."""

import json

import pytest
from eval import coverage_summary
from eval.coverage_eval import CoverageRecord
from eval.e2e_records import E2ERecord

from support_agent.data.doc_models import digest
from test_e2e_resume import meta
from test_eval_tools import eval_item


@pytest.mark.parametrize("corruption", ["missing", "duplicate", "changed"])
def test_summary_validates_coverage_against_frozen_inputs(tmp_path, monkeypatch, corruption):
    monkeypatch.setattr(coverage_summary, "REPO_ROOT", tmp_path)
    case = {
        "id": "one",
        "split": "dev",
        "subset": "controls",
        "scenario": "full",
        "question": "Question?",
        "complete": True,
        "chunks": [],
    }
    inputs = tmp_path / "eval/runs/coverage-round2-inputs.jsonl"
    inputs.parent.mkdir(parents=True)
    inputs.write_text("{}\n" + json.dumps(case) + "\n")
    row = CoverageRecord(
        case=case,
        accepted=False,
        answer="handoff",
        status="model_error",
        error_type="ConnectionError",
        latency_s=1,
    )
    rows = (
        []
        if corruption == "missing"
        else [row, row]
        if corruption == "duplicate"
        else [row.model_copy(update={"case": row.case.model_copy(update={"question": "Altered?"})})]
    )
    run = tmp_path / "run.jsonl"
    run.write_text(
        json.dumps({"inputs_hash": digest(inputs.read_text()), "split": "dev"})
        + "\n"
        + "".join(r.model_dump_json() + "\n" for r in rows)
    )
    with pytest.raises(ValueError, match=r"complete|duplicate"):
        coverage_summary.coverage_run(run)


def test_summary_rejects_duplicate_e2e_rows_before_collapsing_ids(tmp_path):
    row = E2ERecord(item=eval_item("one"), latency_full_answer_s=1)
    run = tmp_path / "run.jsonl"
    run.write_text(meta().model_dump_json() + "\n" + (row.model_dump_json() + "\n") * 2)
    with pytest.raises(ValueError, match="duplicate"):
        coverage_summary.load_run(run)
