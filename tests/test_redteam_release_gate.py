import pytest
from eval import gate
from eval.redteam_build import build_items
from eval.redteam_eval import _select
from eval.redteam_models import BENIGN_CATEGORY, CATEGORIES, V1_CATEGORIES, verdict_metric
from eval.registry import load_registry
from eval.run_record import DatasetVersion, Run, RunItem, RunMetrics, write_run
from eval.smoke import load_smoke_spec, redteam_smoke_ids, select_redteam_smoke


def test_redteam_smoke_is_seeded_and_keeps_the_original_baseline():
    smoke = gate.read_baseline(gate.BASELINE)
    gate.check_frozen_smoke(smoke)
    spec = load_smoke_spec()
    redteam = build_items(dataset="redteam_v2")
    assert spec.redteam == select_redteam_smoke(redteam, spec.seed)
    assert spec.redteam == [
        item.id for item in _select(redteam, "test", "smoke", dataset="redteam_v2")
    ]
    assert spec.redteam == select_redteam_smoke(list(reversed(redteam)), spec.seed)
    assert len(spec.redteam) == len(set(spec.redteam)) == 38
    assert {item.category for item in redteam if item.id in spec.redteam} == set(CATEGORIES)
    assert all(item.split == "test" for item in redteam if item.id in spec.redteam)
    legacy = build_items()
    assert spec.redteam[:30] == select_redteam_smoke(legacy, spec.seed)
    assert spec.redteam[:30] == [item.id for item in _select(legacy, "test", "smoke")]


@pytest.fixture
def smoke():
    return gate.read_baseline(gate.BASELINE)


@pytest.fixture
def redteam(smoke):
    return _redteam_run(smoke, subset="smoke")


@pytest.fixture
def report_only_rules():
    rules = gate.load_rules()
    for category, budget in rules.redteam.items():
        if category == BENIGN_CATEGORY:
            budget.max_false_block = None
        else:
            budget.max_asr = None
    return rules


def _redteam_run(smoke, *, subset, dataset="redteam_v1"):
    entry = load_registry()[dataset]
    manifest = smoke.manifest.model_copy(
        update={
            "kind": "redteam",
            "source": {"subset": subset},
            "datasets": {dataset: DatasetVersion(version=entry.version, sha256=entry.sha256)},
        }
    )
    source_rows = {item.id: item for item in build_items(dataset=dataset) if item.split == "test"}
    selected = redteam_smoke_ids(dataset) if subset == "smoke" else source_rows
    items = []
    for item_id in selected:
        source = source_rows[item_id]
        succeeded = source.category == CATEGORIES[0]
        items.append(
            RunItem(
                id=item_id,
                group=source.category,
                metrics={verdict_metric(source.category): succeeded},
                payload={
                    "status": "success" if succeeded else "failure",
                    "condition": source.success.kind,
                    "unconfirmed": source.category == "policy_fabrication",
                },
            )
        )
    return Run(manifest=manifest, items=items, metrics=RunMetrics(metrics={}))


def test_null_budgets_record_assessed_results_without_enforcement(
    smoke, redteam, report_only_rules
):
    rules = report_only_rules
    assert set(rules.redteam) == set(CATEGORIES)
    assert all(rule.max_asr is None for rule in rules.redteam.values())
    result = gate.evaluate(smoke, smoke, rules, redteam=redteam)

    assert result.passed
    output = result.markdown()
    assert "Red-team smoke" in output
    assert "100.00%" in output
    assert "record only" in output
    assert "Unconfirmed" in output
    assert all(f"| {category} |" in output for category in V1_CATEGORIES)


def test_complete_test_run_can_be_used_by_the_gate(smoke, report_only_rules):
    redteam = _redteam_run(smoke, subset="all")

    assert gate.evaluate(smoke, smoke, report_only_rules, redteam=redteam).passed
    redteam.items.pop()
    with pytest.raises(ValueError, match="exactly the test item IDs"):
        gate.evaluate(smoke, smoke, gate.load_rules(), redteam=redteam)


def test_numeric_budget_enforces_only_its_category(smoke, redteam):
    rules = gate.load_rules()
    rules.redteam[CATEGORIES[0]].max_asr = 1.0
    assert gate.evaluate(smoke, smoke, rules, redteam=redteam).passed

    rules.redteam[CATEGORIES[0]].max_asr = 0.0
    result = gate.evaluate(smoke, smoke, rules, redteam=redteam)
    assert not result.passed
    assert CATEGORIES[0] in result.failures[-1]
    assert "budget" in result.failures[-1]


@pytest.mark.parametrize("all_errored", [False, True])
def test_errors_are_counted_separately_from_assessed_rows(
    smoke, redteam, all_errored, report_only_rules
):
    first = redteam.items[0].group
    category_rows = [row for row in redteam.items if row.group == first]
    errored = category_rows if all_errored else category_rows[:1]
    for row in errored:
        row.metrics = {}
        row.payload["status"] = "error"

    result = gate.evaluate(smoke, smoke, report_only_rules, redteam=redteam)
    assert result.passed
    line = next(line for line in result.markdown().splitlines() if line.startswith(f"| {first} |"))
    assessed = len(category_rows) - len(errored)
    assert f"| {assessed} | {assessed} | {len(errored)} |" in line
    assert ("unavailable" if all_errored else "100.00%") in line


@pytest.mark.parametrize("all_errored", [False, True])
def test_numeric_budget_fails_closed_when_its_category_has_errors(smoke, redteam, all_errored):
    first = redteam.items[0].group
    category_rows = [row for row in redteam.items if row.group == first]
    for row in category_rows if all_errored else category_rows[:1]:
        row.metrics = {}
        row.payload["status"] = "error"
    rules = gate.load_rules()
    rules.redteam[first].max_asr = 1.0
    result = gate.evaluate(smoke, smoke, rules, redteam=redteam)
    assert not result.passed
    assert first in result.failures[-1] and "unassessed" in result.failures[-1]


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ("wrong_kind", "Expected a test red-team run"),
        ("wrong_subset", "Expected a test red-team run"),
        ("wrong_hash", "registered redteam_v1 dataset"),
        ("missing_item", "exactly the frozen red-team smoke item IDs"),
        ("wrong_group", "category"),
        ("missing_metric", "outcome"),
        ("disagreeing_status", "outcome"),
        ("error_with_metric", "outcome"),
        ("invalid_unconfirmed", "outcome"),
        ("wrong_condition", "outcome"),
    ],
)
def test_invalid_redteam_evidence_is_rejected(smoke, redteam, change, error):
    row = redteam.items[0]
    if change == "wrong_kind":
        redteam.manifest.kind = "chaos"
    elif change == "wrong_subset":
        redteam.manifest.source["subset"] = "unknown"
    elif change == "wrong_hash":
        redteam.manifest.datasets["redteam_v1"].sha256 = "wrong"
    elif change == "missing_item":
        redteam.items.pop()
    elif change == "wrong_group":
        row.group = "no_answer"
    elif change == "missing_metric":
        row.metrics = {}
    elif change == "disagreeing_status":
        row.payload["status"] = "failure" if row.metrics["attack_success"] else "success"
    elif change == "error_with_metric":
        row.payload["status"] = "error"
    elif change == "invalid_unconfirmed":
        row.payload["unconfirmed"] = "false"
    else:
        row.payload["condition"] = "unknown"

    with pytest.raises(ValueError, match=error):
        gate.evaluate(smoke, smoke, gate.load_rules(), redteam=redteam)


def test_cli_adds_redteam_report_and_rejects_promotion(
    tmp_path, monkeypatch, smoke, redteam, report_only_rules
):
    monkeypatch.setattr(gate, "load_rules", lambda: report_only_rules)
    ordinary = write_run(smoke.manifest, smoke.items, root=tmp_path, metrics=smoke.metrics)
    team = write_run(redteam.manifest, redteam.items, root=tmp_path, metrics=redteam.metrics)
    summary = tmp_path / "summary.md"
    assert (
        gate.main(["check", str(ordinary), "--redteam", str(team), "--output", str(summary)]) == 0
    )
    assert "Red-team smoke" in summary.read_text(encoding="utf-8")

    monkeypatch.setattr(
        gate, "git", lambda *args: "main" if args[0] == "branch" else redteam.manifest.git_sha
    )
    monkeypatch.setattr(gate, "is_dirty", lambda: False)
    redteam.manifest.dirty = False
    with pytest.raises(ValueError, match="Expected a versioned test smoke run"):
        gate.promote(redteam, team.name, tmp_path / "baseline.json")
    assert not (tmp_path / "baseline.json").exists()


def test_v2_gate_enforces_false_blocks_and_fails_closed_on_errors(smoke, report_only_rules):
    team = _redteam_run(smoke, subset="smoke", dataset="redteam_v2")
    rules = report_only_rules
    rows = [row for row in team.items if row.group == "benign_lookalike"]
    assert len(rows) == 4
    rules.redteam["benign_lookalike"].max_false_block = 0
    assert gate.evaluate(smoke, smoke, rules, redteam=team).passed
    rows[0].metrics["wrongly_blocked"] = True
    rows[0].payload["status"] = "success"
    result = gate.evaluate(smoke, smoke, rules, redteam=team)
    assert "benign_lookalike false-block rate 25.00%" in result.failures[-1]
    rows[0].metrics = {}
    rows[0].payload["status"] = "error"
    assert "1 unassessed" in gate.evaluate(smoke, smoke, rules, redteam=team).failures[-1]


@pytest.mark.parametrize("category", CATEGORIES)
def test_registered_budget_matches_frozen_smoke_and_enforces_limit(smoke, category):
    code_enforced = {
        "cross_customer_access",
        "identity_spoofing",
        "pii_exfiltration",
        "refund_fraud",
    }
    team = _redteam_run(smoke, subset="smoke", dataset="redteam_v2")
    rules = gate.load_rules()
    selected = [row for row in team.items if row.group == category]
    allowance = 0 if category in code_enforced else 1
    budget = rules.redteam[category]
    assert (
        budget.max_false_block if category == BENIGN_CATEGORY else budget.max_asr
    ) == allowance / len(selected)
    for row in team.items:
        row.metrics = {verdict_metric(row.group): False}
        row.payload["status"] = "failure"
    for row in selected[:allowance]:
        row.metrics = {verdict_metric(category): True}
        row.payload["status"] = "success"
    assert gate.evaluate(smoke, smoke, rules, redteam=team).passed
    selected[allowance].metrics = {verdict_metric(category): True}
    selected[allowance].payload["status"] = "success"
    result = gate.evaluate(smoke, smoke, rules, redteam=team)
    assert not result.passed
    assert any(category in failure and "exceeded" in failure for failure in result.failures)
