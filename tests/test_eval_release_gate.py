from pathlib import Path

import pytest
from eval import gate
from eval.run_record import DatasetVersion, Run, RunItem, RunManifest, summarize_metrics


def _run(flipped=0, false_accept=False):
    items = [
        RunItem(
            id=f"supported-{i}",
            group="basic_policy",
            answerable=True,
            metrics={
                "pass_rate": i >= flipped,
                "false_reject": i < flipped,
                "graph_recall_at_5": 1.0,
                "citation_validity": 1.0,
                "latency_p95": 2.0,
            },
        )
        for i in range(40)
    ]
    items += [
        RunItem(
            id=f"unsupported-{i}",
            group="no_answer",
            answerable=False,
            metrics={
                "pass_rate": false_accept and i == 0,
                "false_accept": false_accept and i == 0,
                "latency_p95": 2.0,
            },
        )
        for i in range(30)
    ]
    manifest = RunManifest(
        kind="smoke",
        split="test",
        git_sha="abc123",
        config_hash="config",
        models={},
        datasets={"smoke": DatasetVersion(version="v1", sha256="frozen")},
        seed=17,
        dirty=False,
        started_at=None,
        ended_at=None,
        cost_usd=None,
        cost_note="price not set",
        command=[],
    )
    return Run(manifest=manifest, items=items, metrics=summarize_metrics(items))


@pytest.mark.parametrize(
    ("flips", "accept", "passed"), [(0, True, False), (20, False, False), (2, False, True)]
)
def test_gate_flips(flips, accept, passed):
    assert gate.evaluate(_run(flips, accept), _run(), gate.load_rules()).passed is passed


def test_gate_rejects_noncomparable_runs():
    changed = _run()
    changed.items.pop()
    with pytest.raises(ValueError, match="same item IDs"):
        gate.evaluate(changed, _run(), gate.load_rules())
    changed = _run()
    del changed.items[0].metrics["citation_validity"]
    with pytest.raises(ValueError, match="same observations"):
        gate.evaluate(changed, _run(), gate.load_rules())


def test_baseline_absence_and_protection(tmp_path, monkeypatch):
    path = tmp_path / "baseline.json"
    assert gate.main(["check", "unused", "--baseline", str(path)]) == 2
    monkeypatch.setattr(gate, "git", lambda *args: "feature")
    with pytest.raises(ValueError, match="main"):
        gate.promote(_run(), "run-id", path)
    monkeypatch.setattr(gate, "git", lambda *args: "main" if args[0] == "branch" else "abc123")
    monkeypatch.setattr(gate, "is_dirty", lambda: True)
    with pytest.raises(ValueError, match="clean"):
        gate.promote(_run(), "run-id", path)
    monkeypatch.setattr(gate, "is_dirty", lambda: False)
    monkeypatch.setattr(gate, "check_frozen_smoke", lambda run: None)
    run = _run()
    run.items[0].payload = {"answer": "private content"}
    gate.promote(run, "run-id", path)
    assert "private content" not in path.read_text()
    assert gate.evaluate(run, gate.read_baseline(path), gate.load_rules()).passed
    assert Path(path).exists()


def test_incomplete_run_cannot_represent_the_frozen_benchmark():
    with pytest.raises(ValueError, match="frozen smoke item IDs"):
        gate.check_frozen_smoke(_run())
