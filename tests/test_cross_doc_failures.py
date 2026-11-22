from pathlib import Path

from eval import cross_doc_failures
from eval.e2e_records import E2EMetadata, E2ERecord
from eval.e2e_runs import project
from eval.run_record import RunManifest, RunMetrics
from eval.schema import EvalItem


def _row(case: str, **overrides: object) -> E2ERecord:
    return E2ERecord.model_validate(
        {
            "item": EvalItem(
                id=case,
                group="cross_doc",
                split="test",
                question="Local question text",
                gold_sections=["policy-a", "policy-b"],
                answer_points=["Local answer points"],
                answerable=True,
                source="fixture",
            ),
            "trace": ["classify", "retrieve", "gate"],
            "retrieved_section_ids": [
                "policy-b",
                "policy-b",
                "other",
                "other",
                "other",
                "policy-a",
            ],
            "gate": {"passed": True, "reason": "passed"},
            "coverage": None,
            "latency_full_answer_s": 0,
            **overrides,
        }
    )


def test_report_counts_retrieval_separately_from_gate_and_answer_failures() -> None:
    rows = [
        _row(
            "missing", handoff_reason="incomplete_evidence", answer_status="insufficient_coverage"
        ),
        _row("fixed", trace=["classify", "fixed"], retrieved_section_ids=[], gate=None, path="E"),
        _row("gate", gate={"passed": False, "reason": "low_score"}, handoff_reason="low_evidence"),
        _row(
            "quote",
            answer_status="invalid_evidence",
            retrieved_section_ids=["policy-a", "policy-b"],
        ),
        _row(
            "dependency",
            retrieved_section_ids=[],
            gate={"passed": False, "reason": "empty"},
            retrieval_error_type="DependencyUnavailable",
            handoff_reason="dependency_unavailable",
        ),
        _row("accepted", accepted=True, answer_status="answered", answer="Local answer text"),
    ]

    report = "\n".join(cross_doc_failures.run_results(rows))

    assert "| Accepted | 1 |" in report
    assert "| Rejected before knowledge retrieval | 1 |" in report
    assert "| Reached knowledge retrieval with every gold section in the top 5 | 1 |" in report
    assert "| Rejected with exactly one gold section missing after retrieval | 2 |" in report
    assert "| Rejected with multiple gold sections missing after retrieval | 0 |" in report
    assert "| Rejected with a failed gate | 2 |" in report
    assert "| Coverage marked a part unsupported | 1 |" in report
    assert "| Invalid quote or quote source | 1 |" in report
    assert "| Dependency unavailable | 1 |" in report
    assert "| `missing` | — | yes | `policy-b` | `policy-a` | pass (`passed`)" in report
    assert "| `fixed` | `E` | no | — | `policy-a`, `policy-b` | —" in report
    assert "Local question text" not in report
    assert "Local answer text" not in report


def test_read_saved_run_directory_and_legacy_file(tmp_path: Path) -> None:
    rows = [
        _row("legacy"),
        _row("single", item=_row("single").item.model_copy(update={"group": "basic_policy"})),
    ]
    metadata = E2EMetadata(
        git_sha="abc123",
        config_hash="configuration",
        eval_file_hash="eval-digest",
        corpus_hash="corpus",
        models={"fast": "fixture-model"},
        dataset_versions={"policy": "v1"},
        split="test",
        date="2026-11-22T00:00:00+00:00",
        customer_id="fixture",
        threshold=0.15,
    )
    legacy = tmp_path / "legacy.jsonl"
    legacy.write_text(
        "\n".join([metadata.model_dump_json(), *(r.model_dump_json() for r in rows)]),
        encoding="utf-8",
    )
    manifest = RunManifest(
        kind="smoke",
        split="test",
        git_sha=metadata.git_sha,
        config_hash=metadata.config_hash,
        models=metadata.models,
        datasets={},
        seed=None,
        dirty=False,
        started_at=None,
        ended_at=None,
        cost_usd=None,
        cost_note=None,
        command=[],
        source=metadata.model_dump(),
    )
    (tmp_path / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    (tmp_path / "metrics.json").write_text(
        RunMetrics(metrics={}).model_dump_json(), encoding="utf-8"
    )
    (tmp_path / "items.jsonl").write_text(
        "\n".join(row.model_dump_json() for row in project(rows)), encoding="utf-8"
    )

    report = cross_doc_failures.render_report([legacy, tmp_path])

    assert report.count("| `legacy` |") == 2
    assert "| `single` |" not in report
    assert report.count("Git SHA `abc123`") == 2
    assert report.count("Eval file hash `eval-digest`") == 2
    assert report.count("2026-11-22T00:00:00+00:00") == 2
    assert report.count("fixture-model") == 2
    assert report.count('"policy": "v1"') == 2
