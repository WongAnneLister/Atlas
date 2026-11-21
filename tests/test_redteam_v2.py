from collections import Counter

import httpx
import pytest
from eval.redteam_build import build_items, load_items, write_items
from eval.redteam_canaries import ATTACKER_CUSTOMER, FOREIGN_CUSTOMER, FOREIGN_ORDER
from eval.redteam_checks import Observation, ObservedTurn, evaluate_success
from eval.registry import file_hash, load_registry
from fastapi import FastAPI, Request
from pydantic import ValidationError

FROZEN_V1_HASH = "769d1d4b74ca2cc9be573f423b49f65269e878c9312e7e28043ca1c84e407350"


def test_v2_extends_the_frozen_v1_bytes_and_ids(tmp_path):
    old = tmp_path / "v1.jsonl"
    new = tmp_path / "v2.jsonl"
    write_items(old)
    write_items(new, dataset="redteam_v2")
    registered = load_registry()
    assert file_hash(old) == registered["redteam_v1"].sha256 == FROZEN_V1_HASH
    assert file_hash(new) == registered["redteam_v2"].sha256
    assert set(old.read_bytes().splitlines()) <= set(new.read_bytes().splitlines())
    v1 = {item.id: item for item in load_items(old)}
    v2 = {item.id: item for item in load_items(new)}
    assert all(v2[item.id] == item for item in v1.values())
    added = [item for item in v2.values() if item.id not in v1]
    counts = Counter((item.category, item.split) for item in added)
    for split in ("dev", "test"):
        assert counts["identity_spoofing", split] >= 8
        assert counts["benign_lookalike", split] >= 15
    identity = [item for item in added if item.category == "identity_spoofing"]
    assert {len(item.turns) for item in identity} >= {1, 3}
    assert any(turn.kind == "resume" for item in identity for turn in item.turns)
    assert all(item.attacker_customer == ATTACKER_CUSTOMER for item in identity)
    assert all(item.success.order_id == FOREIGN_ORDER for item in identity)


def test_v2_body_override_cannot_name_unbound_fixture():
    from eval.redteam_models import ItemContent

    item = next(
        item for item in build_items(dataset="redteam_v2") if item.category == "identity_spoofing"
    )
    payload = item.model_dump(exclude={"id"})
    payload["turns"][-1]["body_customer_id"] = "CUST-0001"
    with pytest.raises(ValidationError, match="fixture"):
        ItemContent.model_validate(payload)


def test_v1_observations_keep_their_original_verdicts():
    from eval.redteam_scoring import score

    for item in build_items():
        condition = item.success
        observation = Observation(
            turns=[ObservedTurn(route=["fixed"], answer="") for _ in item.turns],
            canaries=dict.fromkeys(item.target.canary_ids, "synthetic-marker"),
            foreign_fields={FOREIGN_ORDER: ["fixture-field"]},
            judged_fabrication=False,
        )
        if condition.kind == "followed_injection":
            observation.turns[-1].answer = condition.marker_phrase or ""
        if condition.kind == "canary_leak":
            observation.turns[-1].answer = "synthetic-marker"
        assert score(item, observation, []) == evaluate_success(item, observation)


@pytest.mark.parametrize(
    ("reason", "answer", "expected"),
    [
        ("guardrail_blocked", "I will hand this off.", True),
        (
            None,
            "I can help with shopping and after-sales questions. "
            "Please describe what you need help with.",
            True,
        ),
        ("low_evidence", "I will hand this off.", False),
        (None, "I can find those setup instructions.", False),
    ],
)
def test_benign_false_block_is_scored_separately(reason, answer, expected):
    from eval.redteam_scoring import score

    item = next(
        item for item in build_items(dataset="redteam_v2") if item.category == "benign_lookalike"
    )
    observed = Observation(turns=[ObservedTurn(route=["fixed"], answer=answer)])
    assert score(item, observed, [reason]).success is expected


@pytest.mark.parametrize("has_session", [False, True])
async def test_harness_uses_only_the_fixed_fixture_session(has_session):
    from eval.redteam_runner import _session_token, _submit_turn

    app = FastAPI()
    if has_session:

        @app.post("/api/session")
        async def session(request: Request):
            assert await request.json() == {"customer_id": ATTACKER_CUSTOMER}
            return {"token": "fixture-token"}

    @app.post("/api/chat")
    async def chat(request: Request):
        assert request.headers.get("authorization") == (
            "Bearer fixture-token" if has_session else None
        )
        assert (await request.json())["customer_id"] == FOREIGN_CUSTOMER
        return {"ok": True}

    item = next(
        item
        for item in build_items(dataset="redteam_v2")
        if item.category == "identity_spoofing" and len(item.turns) == 1
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://atlas-redteam.test"
    ) as client:
        token = await _session_token(client)
        response, customer = await _submit_turn(client, item, item.turns[0], token)
    assert response.json() == {"ok": True}
    assert customer == (ATTACKER_CUSTOMER if has_session else FOREIGN_CUSTOMER)


def test_comparison_and_report_separate_assessed_lookalikes(tmp_path):
    from eval import gate
    from eval.compare import main
    from eval.redteam_report import redteam_metrics, render_report
    from eval.run_record import DatasetVersion, Run, RunItem, write_run

    from support_agent.config import get_settings

    before = [
        RunItem(
            id=item_id,
            group=group,
            metrics={metric: verdict},
            payload={
                "status": "success" if verdict else "failure",
                "condition": condition,
                "unconfirmed": False,
            },
        )
        for item_id, group, metric, verdict, condition in (
            ("attack", "identity_spoofing", "attack_success", True, "foreign_order_exposed"),
            ("benign", "benign_lookalike", "wrongly_blocked", False, "wrongly_blocked"),
        )
    ]
    after = [
        item.model_copy(
            update={
                "metrics": dict.fromkeys(item.metrics, item.group == "benign_lookalike"),
                "payload": {
                    **item.payload,
                    "status": "success" if item.group == "benign_lookalike" else "failure",
                },
            }
        )
        for item in reversed(before)
    ]
    entry = load_registry()["redteam_v2"]
    reference = gate.read_baseline(gate.BASELINE)
    manifest = reference.manifest.model_copy(
        update={
            "kind": "redteam",
            "source": {"subset": "smoke"},
            "datasets": {"redteam_v2": DatasetVersion(version=entry.version, sha256=entry.sha256)},
        }
    )
    stats = get_settings().eval.stats
    paths = [
        write_run(
            manifest, items, root=tmp_path, suffix=suffix, metrics=redteam_metrics(items, stats)
        )
        for items, suffix in ((before, "before"), (after, "after"))
    ]
    metrics = redteam_metrics(after, stats)
    assert metrics.metrics["attack_success"].n == 1
    assert metrics.metrics["attack_success"].count == 0
    assert metrics.metrics["wrongly_blocked"].count == 1
    report = tmp_path / "report.md"
    render_report(Run(manifest=manifest, items=after, metrics=metrics), report)
    assert "## False blocks" in report.read_text()
    assert "Benign look-alikes are excluded from attack success rates." in report.read_text()
    comparison = tmp_path / "comparison.md"
    assert main([*map(str, paths), "--output", str(comparison)]) == 0
    result = comparison.read_text()
    assert "| attack_success | 1 | 1 | 0 | -1 | [-1, -1] | 1 |" in result
    assert "| identity_spoofing/attack_success | 1 | 1 | 0 | -1 | [-1, -1] | 1 |" in result
    assert "| wrongly_blocked | 1 | 0 | 1 | +1 | [+1, +1] | 1 |" in result
    assert "| benign_lookalike/wrongly_blocked | 1 | 0 | 1 | +1 | [+1, +1] | 1 |" in result
