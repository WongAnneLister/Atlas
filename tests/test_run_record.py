from datetime import UTC, datetime

import pytest
from eval.run_record import DatasetVersion, RunItem, RunManifest, read_run, write_run


def test_round_trip_and_no_overwrite(tmp_path):
    timestamp = datetime(2026, 11, 19, tzinfo=UTC)
    manifest = RunManifest(
        kind="e2e",
        split="test",
        git_sha="19eeb53",
        config_hash="config",
        models={"main": "model"},
        datasets={"smoke": DatasetVersion(version="v1", sha256="hash")},
        seed=17,
        dirty=False,
        started_at=timestamp,
        ended_at=timestamp,
        cost_usd=None,
        cost_note="price not set",
        command=["eval-e2e"],
    )
    items = [RunItem(id="item", metrics={"false_accept": False}, payload={"local": "text"})]
    path = write_run(manifest, items, root=tmp_path)
    run = read_run(path)
    assert run.manifest == manifest
    assert run.items == items
    summary = run.metrics.metrics["false_accept"]
    assert summary.count == 0
    assert summary.n == 1
    assert not any(
        "text" in (path / name).read_text() for name in ("manifest.json", "metrics.json")
    )
    with pytest.raises(FileExistsError):
        write_run(manifest, items, root=tmp_path)


def test_legacy_e2e_projection_preserves_metrics(tmp_path):
    from eval.e2e_records import E2EMetadata, E2ERecord
    from eval.e2e_report import render_e2e
    from eval.e2e_runs import import_e2e, project
    from eval.schema import EvalItem

    metadata = E2EMetadata(
        git_sha="abc123",
        config_hash="config",
        eval_file_hash="frozen",
        corpus_hash="corpus",
        models={"main": "model"},
        dataset_versions={},
        split="test",
        date="2026-11-19T00:00:00+00:00",
        customer_id="fixture",
        threshold=0.15,
    )
    item = EvalItem(
        id="no-answer",
        group="no_answer",
        split="test",
        question="Where is Mars?",
        gold_sections=[],
        answer_points=[],
        answerable=False,
        reviewed=False,
        source="fixture",
    )
    record = E2ERecord(item=item, accepted=False, latency_full_answer_s=1.5)
    legacy = tmp_path / "legacy.jsonl"
    legacy.write_text(metadata.model_dump_json() + "\n" + record.model_dump_json() + "\n")
    run = read_run(import_e2e(legacy, root=tmp_path))
    assert run.items == project([record])
    assert run.metrics.metrics["latency_p95"].interval.point == 1.5
    assert run.metrics.metrics["false_accept"].count == 0

    report = tmp_path / "e2e.md"
    render_e2e(run, report)
    assert "| Latency P95 full answer | 1.5000s |" in report.read_text()
    assert "Wilson" in report.read_text()


def test_saved_interval_keeps_its_confidence_level(tmp_path, monkeypatch):
    from eval.run_record import confidence_level, summarize_metrics

    monkeypatch.setenv("SUPPORT_AGENT__EVAL__STATS__ALPHA", "0.10")
    from support_agent.config import get_settings

    get_settings.cache_clear()
    try:
        metrics = summarize_metrics([RunItem(id="item", metrics={"value": True})])
    finally:
        monkeypatch.delenv("SUPPORT_AGENT__EVAL__STATS__ALPHA")
        get_settings.cache_clear()
    assert confidence_level(metrics) == 0.9
