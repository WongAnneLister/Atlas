from pathlib import Path

from eval.legacy_core import (
    import_intent,
    import_retrieval,
    render_intent,
    render_retrieval,
    retrieval_items,
)
from eval.retrieval_csv_runs import import_retrieval_csv
from eval.retrieval_records import RetrievalRun, SearchRecord
from eval.run_record import read_run
from eval.sweep import GateScore, GateScoreMetadata
from eval.sweep_runs import import_sweep, render_sweep

from support_agent.graph.intents import Intent
from test_intent_eval import record
from test_retrieval_experiment import metadata as retrieval_metadata
from test_retrieval_experiment import question


def test_intent_legacy_import_preserves_measured_accuracy(tmp_path: Path) -> None:
    import json

    metadata = {
        "git_sha": "a" * 40,
        "code_hash": "code",
        "config_hash": "b" * 64,
        "prompt_hash": "prompt",
        "dataset_hash": "c" * 64,
        "date": "2026-11-10T00:30:32.629594+00:00",
        "model": "fake-model",
        "provider": "fake-provider",
        "dataset_versions": {},
        "target_accuracy": 0.9,
        "sample_stats": {},
        "response_models": ["fake-model"],
        "model_options": {},
    }
    rows = [
        record(Intent.ORDER_STATUS, Intent.ORDER_STATUS, "a"),
        record(Intent.ORDER_STATUS, Intent.SHIPPING_DELIVERY, "b"),
    ]
    source = tmp_path / "legacy.json"
    source.write_text(
        json.dumps({"metadata": metadata, "records": [r.model_dump(mode="json") for r in rows]})
    )
    run_dir = import_intent(source, root=tmp_path / "runs")
    source.unlink()
    run = read_run(run_dir)
    assert run.manifest.git_sha == metadata["git_sha"]
    assert run.manifest.ended_at is None
    assert run.metrics.metrics["accuracy"].interval.point == 0.5
    assert run.metrics.metrics["path_accuracy"].interval.point == 1.0
    assert run.metrics.metrics["macro_precision"].interval.point == 1 / len(Intent)
    assert run.metrics.metrics["macro_recall"].interval.point == 0.5 / len(Intent)
    output = tmp_path / "report.md"
    render_intent(run_dir, output)
    assert "| Intent accuracy | 0.5000 |" in output.read_text()


def test_retrieval_run_items_have_unique_pairs_and_retain_per_query_metrics() -> None:
    item = question()
    rows = [
        SearchRecord(
            item=item,
            mode=mode,
            chunks=[],
            latency_s=1.25,
            components_s={},
            provenance="fixture",
        )
        for mode in ("dense", "bm25")
    ]
    measured = retrieval_items(rows, [1, 3, 5])
    assert len({r.id for r in measured}) == 2
    assert measured[0].metrics["dev.dense.overall.recall@5"] == 0.0
    assert measured[1].metrics["dev.bm25.overall.mean_latency_s"] == 1.25


def test_sweep_legacy_import_replays_frozen_scores(tmp_path: Path) -> None:
    dev_path = tmp_path / "dev.jsonl"
    test_path = tmp_path / "test.jsonl"
    for path, split, value in ((dev_path, "dev", 0.10), (test_path, "test", 0.70)):
        meta = GateScoreMetadata(
            git_sha="a" * 40,
            config_hash="b" * 64,
            eval_file_hash="c" * 64,
            corpus_hash="d" * 64,
            split=split,
            date="2026-11-10T00:00:00+00:00",
            models={},
            dataset_versions={},
        )
        rows = [
            GateScore(
                id=f"{split}-unsafe",
                group="no_answer",
                split=split,
                answerable=False,
                score=value,
                signals={},
            ),
            GateScore(
                id=f"{split}-safe",
                group="basic_policy",
                split=split,
                answerable=True,
                score=0.50,
                signals={},
            ),
        ]
        path.write_text(
            meta.model_dump_json() + "\n" + "\n".join(row.model_dump_json() for row in rows)
        )
    run_dir = import_sweep(dev_path, test_path, rule="midpoint", root=tmp_path / "runs")
    dev_path.unlink()
    test_path.unlink()
    run = read_run(run_dir)
    assert run.metrics.metrics["test.false_accept"].interval.point == 1.0
    output = tmp_path / "report.md"
    render_sweep(run_dir, output)
    assert "Selected threshold: **0.30**" in output.read_text()
    assert "test-unsafe" in output.read_text()


def test_retrieval_csv_import_agrees_with_full_record(tmp_path: Path) -> None:
    record = SearchRecord(
        item=question(),
        mode="dense",
        chunks=[],
        latency_s=1.25,
        components_s={},
        provenance="fixture",
    )
    retrieval = RetrievalRun(metadata=retrieval_metadata(), requested_split="dev", records=[record])
    legacy = tmp_path / "retrieval.json"
    legacy.write_text(retrieval.model_dump_json())
    root = tmp_path / "runs"
    full_path = import_retrieval(legacy, root=root, suffix="full")
    legacy.unlink()
    reports = tmp_path / "reports"
    render_retrieval(full_path, reports, tmp_path / "RETRIEVAL.md")
    csv_path = import_retrieval_csv(
        [reports / "retrieval_dev.csv"], reports / "retrieval.md", root=root, suffix="csv"
    )
    assert read_run(full_path).metrics == read_run(csv_path).metrics
