from __future__ import annotations

import csv
from pathlib import Path

from eval import compare
from eval.e2e_records import E2EMetadata, JudgeRecord
from eval.e2e_runs import prepare_e2e, unpack
from eval.multipart_eval import collect, write_human_sample, write_report
from eval.run_record import DatasetVersion, read_run, write_run
from eval.schema import MultipartItem, MultipartPart

from support_agent.config import Settings


def test_collect_report_and_review_with_a_fake_graph(tmp_path: Path, monkeypatch) -> None:
    item = MultipartItem(
        id="multi-dev-1",
        split="dev",
        group="half_answerable",
        question="What is the return window, and can I pay in gold?",
        source="fixture",
        parts=[
            MultipartPart(
                text="What is the return window?",
                gold_sections=["returns"],
                answer_points=["30 days"],
                answerable=True,
                source_item_id="dev-return",
            ),
            MultipartPart(
                text="Can I pay in gold?",
                gold_sections=[],
                answer_points=[],
                answerable=False,
                source_item_id="dev-gold",
            ),
        ],
    )

    class Graph:
        def invoke(self, state, config):
            assert state["messages"][0].content == item.question
            assert state["customer_id"] == settings.evaluation.customer_id
            assert config["configurable"]["thread_id"]
            return {
                "trace": ["answer", "handoff"],
                "answer_status": "partial",
                "answer": "Returns are allowed within 30 days. The payment question needs review.",
                "handoff": {"reason": "insufficient_coverage"},
                "parts": [
                    {
                        "text": item.parts[0].text,
                        "gate": {"passed": True},
                        "retrieved_section_ids": ["returns"],
                        "cited_section_ids": ["returns"],
                        "answered": True,
                    },
                    {
                        "text": item.parts[1].text,
                        "gate": {"passed": False},
                        "retrieved_section_ids": ["payments"],
                        "retrieved_sources": [{"section_id": "payments", "text": "Card payments."}],
                        "handed_off": True,
                    },
                ],
            }

    settings = Settings()
    records = collect(Graph(), [item], settings, None)
    assert not records[0].accepted
    assert records[0].parts and records[0].parts[0].gate == {"passed": True}

    metadata = E2EMetadata(
        git_sha="fixture",
        config_hash="config",
        eval_file_hash="dataset",
        corpus_hash="corpus",
        models={"main": "fixture"},
        dataset_versions={"fixture": "frozen"},
        split="dev",
        date="2026-11-22T00:00:00Z",
        customer_id=settings.evaluation.customer_id,
        threshold=0.5,
    )
    monkeypatch.setattr(
        "eval.e2e_runs.dataset_version",
        lambda sha: {"multipart_v1": DatasetVersion(version="v1", sha256=sha)},
    )
    run = prepare_e2e(metadata, records, dirty=False)
    assert run.manifest.kind == "multipart"
    assert run.items[0].metrics["partial_answer_rate"] is True
    assert run.items[0].metrics["answered_part_correct"] is True
    assert run.items[0].metrics["unanswerable_part_handed_off"] is True
    path = write_run(run.manifest, run.items, root=tmp_path, metrics=run.metrics)
    replay = read_run(path)
    report = tmp_path / "report.md"
    write_report(replay, report)
    assert "| dev | half_answerable | partial_answer_rate | 1/1" in report.read_text()
    assert unpack(replay)[1] == records
    comparison = tmp_path / "compare.md"
    assert compare.main([str(path), str(path), "--output", str(comparison)]) == 0
    assert "half_answerable/partial_answer_rate" in comparison.read_text()
    sample = tmp_path / "review.csv"
    write_human_sample(
        records, sample, seed=1, size=1, judged=[JudgeRecord(item_id=item.id, flagged=True)]
    )
    (row,) = list(csv.DictReader(sample.read_text().splitlines()))
    assert row["item_id"] == item.id
    assert row["judge_flagged"] == "true"
    assert "Card payments." in row["parts"]
    assert row["answered_parts_correct"] == ""
    assert row["handoffs_supported_by_evidence"] == ""
