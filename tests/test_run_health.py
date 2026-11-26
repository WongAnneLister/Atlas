"""A run whose model or dependency calls all failed must not produce a normal report."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from eval import e2e_eval
from eval.e2e_records import E2EMetadata
from eval.e2e_runs import prepare_e2e
from eval.multipart_eval import collect
from eval.run_health import INVALID_RUN_STATUS, invalid_run_message
from eval.run_record import DatasetVersion
from eval.schema import MultipartItem, MultipartPart

from support_agent.config import Settings
from support_agent.observability.cost import UsageLedger
from test_e2e_speed import _eval_item, _settings


def _broken(row: Any) -> dict[str, Any]:
    # What a missing provider package looks like: classify fails, the graph falls back.
    return {
        "trace": ["input_guard", "rewrite", "classify", "chitchat"],
        "answer": "Hi! I can help with orders, refunds and policies.",
        "classification_failed": True,
        "classification_error_type": "ImportError",
    }


def test_e2e_refuses_to_report_a_run_where_every_model_call_failed(
    tmp_path: Path, monkeypatch
) -> None:
    items = [_eval_item(index) for index in range(4)]
    eval_file = tmp_path / "items.jsonl"
    eval_file.write_text("".join(f"{row.model_dump_json()}\n" for row in items))
    (tmp_path / "manifest.json").write_text('{"corpus_hash": "corpus-hash"}')
    settings = _settings(tmp_path)
    settings.evaluation.sets_dir = str(tmp_path)
    monkeypatch.setattr(e2e_eval, "get_settings", lambda: settings)
    monkeypatch.setattr(e2e_eval, "is_dirty", lambda: False)
    monkeypatch.setattr(e2e_eval, "_git_sha", lambda: "clean-sha")
    monkeypatch.setattr(e2e_eval, "configured_build_id", lambda settings: None)

    class FakeDeps:
        def __init__(self, settings: Settings, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> FakeDeps:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(e2e_eval, "GraphDeps", FakeDeps)
    monkeypatch.setattr(e2e_eval, "build_graph", lambda deps: deps)
    monkeypatch.setattr(
        e2e_eval, "_run_item", lambda graph, row, *args: (_broken(row), 1.0, UsageLedger())
    )
    output, report, pointer = tmp_path / "run.jsonl", tmp_path / "run.md", tmp_path / "run.txt"
    status = e2e_eval.main(
        [
            "--allow-untuned",
            "--eval-file",
            str(eval_file),
            "--output",
            str(output),
            "--report",
            str(report),
            "--run-root",
            str(tmp_path / "runs"),
            "--run-pointer",
            str(pointer),
        ]
    )
    assert status == INVALID_RUN_STATUS
    assert not report.exists() and not pointer.exists() and not (tmp_path / "runs").exists()
    # The rows are kept for debugging but cannot be resumed by the next attempt.
    assert not output.exists() and output.with_suffix(".jsonl.invalid").exists()


def _multipart_run(graph_result: dict[str, Any], monkeypatch) -> Any:
    item = MultipartItem(
        id="multi-dev-1",
        split="dev",
        group="both_unanswerable",
        question="Can I pay in gold, and can I pay in silver?",
        source="fixture",
        parts=[
            MultipartPart(
                text=text,
                gold_sections=[],
                answer_points=[],
                answerable=False,
                source_item_id=f"dev-{n}",
            )
            for n, text in enumerate(["Can I pay in gold?", "Can I pay in silver?"])
        ],
    )

    class Graph:
        def invoke(self, state: Any, config: Any) -> dict[str, Any]:
            return graph_result

    settings = Settings()
    records = collect(Graph(), [item], settings, None)
    metadata = E2EMetadata(
        git_sha="fixture",
        config_hash="config",
        eval_file_hash="dataset",
        corpus_hash="corpus",
        models={"main": "fixture"},
        dataset_versions={"fixture": "frozen"},
        split="dev",
        date="2026-11-26T00:00:00Z",
        customer_id=settings.evaluation.customer_id,
        threshold=0.5,
    )
    monkeypatch.setattr(
        "eval.e2e_runs.dataset_version",
        lambda sha: {"multipart_v1": DatasetVersion(version="v1", sha256=sha)},
    )
    return prepare_e2e(metadata, records, dirty=False)


def test_invalid_run_rule_flags_failed_calls_and_passes_handoffs(monkeypatch) -> None:
    broken = _multipart_run(_broken(None), monkeypatch)
    message = invalid_run_message(broken)
    assert message is not None and "ImportError x1" in message

    # An ordinary handoff is a measured outcome, not a broken run.
    healthy = _multipart_run(
        {"trace": ["gate", "handoff"], "handoff": {"reason": "low_evidence"}}, monkeypatch
    )
    assert invalid_run_message(healthy) is None
