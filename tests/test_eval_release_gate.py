from pathlib import Path

import pytest
from eval import gate
from eval.run_record import DatasetVersion, Run, RunItem, RunManifest, summarize_metrics


def _run(flipped=0, false_accept=False, latency=2.0):
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
                "latency_p95": latency,
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
                "latency_p95": latency,
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


def test_latency_regression_is_reported_but_does_not_fail_the_gate():
    result = gate.evaluate(_run(latency=9.0), _run(), gate.load_rules())
    latency = next(row for row in result.comparisons if row.name == "latency_p95")
    assert latency.verdict == "worse"
    assert result.passed
    assert "report only" in result.markdown()


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


def _promotable(monkeypatch):
    monkeypatch.setattr(gate, "git", lambda *args: "main" if args[0] == "branch" else "abc123")
    monkeypatch.setattr(gate, "is_dirty", lambda: False)
    monkeypatch.setattr(gate, "check_frozen_smoke", lambda run: None)


def test_promotion_rejects_a_run_broken_by_dependency_errors(tmp_path, monkeypatch):
    _promotable(monkeypatch)
    run = _run()
    for row in run.items:
        row.payload = {"classification_error_type": "APIStatusError"}
    path = tmp_path / "baseline.json"
    with pytest.raises(ValueError, match="dependency errors on 70/70 items"):
        gate.promote(run, "run-id", path)
    assert not path.exists()


def test_promotion_allows_a_few_dependency_errors(tmp_path, monkeypatch):
    _promotable(monkeypatch)
    run = _run()
    run.items[0].payload = {"retrieval_error_type": "MilvusException"}
    run.items[1].payload = {"answer_error_type": "ValidationError"}
    gate.promote(run, "run-id", tmp_path / "baseline.json")
    assert (tmp_path / "baseline.json").exists()
