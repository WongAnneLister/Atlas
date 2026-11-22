from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from eval import chaos, e2e_eval, registry
from eval.e2e_speed import run_config_hash
from eval.run_record import read_run
from eval.schema import EvalItem
from eval.smoke import SMOKE_PATH, SmokeSpec

from support_agent.config import get_settings
from support_agent.observability.cost import UsageLedger
from support_agent.reliability.events import ReliabilityEvent


def test_ordinary_e2e_cannot_collect_fault_injected_smoke(monkeypatch, capsys):
    loaded = get_settings()
    settings = loaded.model_copy(
        update={"chaos": loaded.chaos.model_copy(update={"enabled": True})}
    )
    monkeypatch.setattr(e2e_eval, "get_settings", lambda: settings)

    with pytest.raises(SystemExit) as error:
        e2e_eval.main([])
    assert error.value.code == 2
    assert "make chaos" in capsys.readouterr().err


def _item(item_id: str) -> EvalItem:
    group = item_id.partition("-")[0]
    answerable = group != "no_answer"
    return EvalItem(
        id=item_id,
        group=group,
        split="test",
        question="Local test question",
        gold_sections=["section-one", "section-two"] if answerable else [],
        answer_points=["local answer"] if answerable else [],
        answerable=answerable,
        source="fixture",
    )


@pytest.mark.parametrize("false_accept", [False, True])
def test_chaos_records_validated_overlay_provenance_and_full_outcomes(
    false_accept, tmp_path, monkeypatch
):
    ids = SmokeSpec.model_validate(yaml.safe_load(SMOKE_PATH.read_text())).item_ids
    rows = [_item(item_id) for item_id in ids]
    smoke_file = tmp_path / "smoke.jsonl"
    smoke_file.write_text("".join(f"{row.model_dump_json()}\n" for row in rows))
    smoke = registry.load_registry()["smoke"].model_copy(
        update={"path": Path("smoke.jsonl"), "sha256": registry.file_hash(smoke_file)}
    )
    monkeypatch.setattr(registry, "load_registry", lambda: {"smoke": smoke})
    monkeypatch.setattr(e2e_eval, "is_dirty", lambda: False)
    monkeypatch.setattr(e2e_eval, "_git_sha", lambda: "clean-sha")
    (tmp_path / "manifest.json").write_text('{"corpus_hash": "corpus-hash"}')
    monkeypatch.setenv("SUPPORT_AGENT__EVALUATION__SETS_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MAIN_MODEL", "fake-main")
    monkeypatch.setenv("LLM_MAIN_FALLBACKS", "fake-fallback, fake-main, fake-fallback")
    monkeypatch.setenv("SUPPORT_AGENT__RELIABILITY__LOCKS__CONVERSATION_TTL_S", "6000")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_BASE", "https://fake-relay.example/ignored-endpoint-path")

    config_path = tmp_path / "chaos.yaml"
    config_path.write_text("chaos:\n  enabled: true\n  seed: 24\n  llm_timeout_rate: 0.2\n")
    settings_seen = []
    first_no_answer = next(row.id for row in rows if not row.answerable)

    class FakeDeps:
        def __init__(self, settings, **kwargs):
            settings_seen.append(settings)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    def fake_item(graph, item, customer_id, thread_id, trace):
        usage = UsageLedger()
        if item.id == ids[0]:
            return (
                {
                    "handoff": SimpleNamespace(reason="dependency_unavailable"),
                    "retrieval_error_type": "InjectedTimeout",
                    "reliability_events": [
                        ReliabilityEvent(
                            call_site="retrieve", dependency="milvus", attempts=3, retries=2
                        ),
                        ReliabilityEvent(
                            call_site="classify",
                            dependency="llm:fake-main",
                            attempts=3,
                            retries=1,
                            fell_back=True,
                            repaired=True,
                        ),
                    ],
                },
                1.0,
                usage,
            )
        if false_accept and item.id == first_no_answer:
            return {"answer": "local answer", "trace": ["answer"]}, 1.0, usage
        return {}, 1.0, usage

    monkeypatch.setattr(e2e_eval, "GraphDeps", FakeDeps)
    monkeypatch.setattr(e2e_eval, "build_graph", lambda deps: object())
    monkeypatch.setattr(e2e_eval, "_run_item", fake_item)
    run_pointer = tmp_path / "run.txt"
    report = tmp_path / "report.md"
    status = chaos.main(
        [
            "--config",
            str(config_path),
            "--eval-file",
            str(smoke_file),
            "--run-root",
            str(tmp_path / "runs"),
            "--run-pointer",
            str(run_pointer),
            "--run-suffix",
            "test",
            "--report",
            str(report),
        ]
    )

    assert status == int(false_accept)
    run_dir = Path(run_pointer.read_text().strip())
    assert run_dir.name.startswith("chaos-test-")
    run = read_run(run_dir)
    assert run.manifest.kind == "chaos"
    assert run.manifest.git_sha == "clean-sha"
    assert run.manifest.dirty is False
    assert run.manifest.datasets["smoke"].sha256 == smoke.sha256
    assert run.manifest.models["main"] == "fake-main"
    assert run.manifest.models["main_fallback_1"] == "fake-fallback"
    assert "main_fallback_2" not in run.manifest.models
    assert run.manifest.source["chaos"]["seed"] == 24
    assert run.manifest.source["endpoint_host"] == "fake-relay.example"
    assert run.manifest.config_hash == run_config_hash(settings_seen[0])
    assert settings_seen[0].chaos.llm_timeout_rate == 0.2
    assert run.items[0].payload["retrieval_error_type"] == "InjectedTimeout"
    result = report.read_text()
    assert "dependency_unavailable | 1" in result
    assert "Retries | 3" in result
    assert "Fallbacks | 1" in result
    assert "Repairs | 1" in result
    assert f"{int(false_accept)}/30" in result
    if false_accept:
        assert "release blocker" in result
    else:
        assert "rule of three" in result
        assert "Wilson" in result
    assert "fake-relay.example" in result
    assert "ignored-endpoint-path" not in (run_dir / "manifest.json").read_text()
    assert "Local test question" not in result
    assert "Local test question" not in (run_dir / "manifest.json").read_text()
    assert "Local test question" not in (run_dir / "metrics.json").read_text()

    (run_dir / "items.jsonl").unlink()
    replay = tmp_path / "replay.md"
    assert chaos.main(["--run-dir", str(run_dir), "--report", str(replay)]) == status
    assert replay.read_text() == result


def test_overlay_revalidates_production_settings_before_collection(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://fixture:private@localhost/fixture")
    get_settings.cache_clear()
    config = tmp_path / "chaos.yaml"
    config.write_text("chaos:\n  enabled: true\n")

    try:
        with pytest.raises(SystemExit) as error:
            chaos.main(["--config", str(config)])
    finally:
        get_settings.cache_clear()

    assert error.value.code == 2
    output = capsys.readouterr().err
    assert "prod" in output and "chaos" in output
    assert "private" not in output
