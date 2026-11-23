"""Offline unit tests for Commit 32 (online feedback, stratified review, drift monitoring)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from scripts.replay_traffic import run_simulated_week

from support_agent.api.app import create_app
from support_agent.api.deps import ApiDeps
from support_agent.config import get_settings
from support_agent.graph.deps import GraphDeps
from support_agent.observability.drift import (
    compute_categorical_psi,
    compute_continuous_psi,
    compute_ks_statistic,
    evaluate_drift,
    export_drift_gauges,
)
from support_agent.observability.metrics import AtlasMetrics
from support_agent.observability.online_checks import check_citation_validity
from support_agent.observability.online_settings import DriftThresholdSettings
from support_agent.observability.online_store import (
    FeedbackRecord,
    OnlineEvalStore,
    TurnEventRecord,
)
from support_agent.observability.sampler import export_review_candidates, sample_for_review
from support_agent.orders.models import CustomerSummary


def test_psi_and_ks_on_known_distributions() -> None:
    # Identical discrete distributions -> PSI == 0
    base = {"policy_question": 50, "product_question": 30, "order_status": 20}
    assert compute_categorical_psi(base, base) == pytest.approx(0.0, abs=1e-9)

    # Shifted discrete distribution -> PSI > 0.20
    shifted = {"policy_question": 90, "product_question": 5, "order_status": 5}
    assert compute_categorical_psi(base, shifted) > 0.20

    # Identical continuous distributions -> KS == 0, PSI == 0
    ref_scores = [0.60, 0.65, 0.70, 0.75, 0.80] * 10
    assert compute_ks_statistic(ref_scores, ref_scores) == pytest.approx(0.0, abs=1e-9)
    assert compute_continuous_psi(ref_scores, ref_scores) == pytest.approx(0.0, abs=1e-9)

    # Completely separated distributions -> KS == 1.0
    low_scores = [0.05, 0.08, 0.10, 0.12, 0.14] * 10
    assert compute_ks_statistic(ref_scores, low_scores) == pytest.approx(1.0)
    assert compute_continuous_psi(ref_scores, low_scores) > 0.50


def test_drift_breach_logic_and_prometheus_gauges() -> None:
    t0 = datetime(2026, 11, 16, 10, 0, tzinfo=UTC)
    ref_events = [
        TurnEventRecord(
            id=f"r-{i}",
            conversation_id=f"rc-{i}",
            customer_id="C1",
            intent="order_status" if i % 2 == 0 else "product_question",
            path="knowledge",
            gate_score=0.75,
            gate_passed=True,
            handoff_reason=None,
            rewrite_skipped=True,
            tokens_total=2000,
            cost_usd=0.002,
            created_at=t0 + timedelta(minutes=i),
        )
        for i in range(40)
    ]
    cur_events = [
        TurnEventRecord(
            id=f"c-{i}",
            conversation_id=f"cc-{i}",
            customer_id="C1",
            intent="policy_question",
            path="knowledge",
            gate_score=0.08,
            gate_passed=False,
            handoff_reason="low_evidence",
            rewrite_skipped=False,
            tokens_total=4000,
            cost_usd=0.005,
            created_at=t0 + timedelta(days=5, minutes=i),
        )
        for i in range(40)
    ]
    ref_fb = [
        FeedbackRecord(
            id=f"rf-{i}",
            message_id=f"rm-{i}",
            conversation_id=f"rc-{i}",
            customer_id="C1",
            rating="up",
            created_at=t0,
        )
        for i in range(20)
    ]
    cur_fb = [
        FeedbackRecord(
            id=f"cf-{i}",
            message_id=f"cm-{i}",
            conversation_id=f"cc-{i}",
            customer_id="C1",
            rating="down",
            created_at=t0 + timedelta(days=5),
        )
        for i in range(20)
    ]

    thresholds = DriftThresholdSettings()
    report = evaluate_drift(ref_events, cur_events, ref_fb, cur_fb, thresholds)
    assert len(report.breaches) == len(report.signals)

    # Identical windows -> 0 breaches
    no_drift = evaluate_drift(ref_events, ref_events, ref_fb, ref_fb, thresholds)
    assert len(no_drift.breaches) == 0

    # Export to Prometheus gauges
    settings = get_settings()
    metrics = AtlasMetrics(settings)
    export_drift_gauges(report, metrics)
    assert metrics.drift.labels("gate_score_ks")._value.get() == pytest.approx(1.0)


def test_feedback_idempotency_and_api_reviews() -> None:
    store = OnlineEvalStore.from_sqlite_path(":memory:")
    rec1, created1 = store.record_feedback(
        message_id="msg-1",
        conversation_id="conv-1",
        customer_id="CUST-1",
        rating="down",
        reason="Missing details for alice@example.com",
    )
    assert created1 is True
    assert "[EMAIL]" in (rec1.reason or "")

    # Replay with same message_id is idempotent
    rec2, created2 = store.record_feedback(
        message_id="msg-1",
        conversation_id="conv-1",
        customer_id="CUST-1",
        rating="up",
    )
    assert created2 is False
    assert rec2.id == rec1.id
    assert len(store.list_feedback()) == 1

    # Also test via FastAPI endpoints
    class _FakeOrders:
        def list_customers(self, limit: int = 10) -> list[CustomerSummary]:
            return [CustomerSummary(customer_id="CUST-1", name="Alice", email="a@example.com")]

    settings = get_settings().model_copy(deep=True)
    settings.online_eval.enabled = True
    settings.handoff.demo_agent_token = "agent-secret"
    graph_deps = GraphDeps(settings=settings, online_eval_store=store)
    api_deps = ApiDeps(
        settings=settings,
        graph_deps=graph_deps,
        order_service=_FakeOrders(),  # type: ignore[arg-type]
        milvus_check=lambda: True,
        warmup=False,
    )
    app = create_app(api_deps)
    with TestClient(app) as client:
        assert client.post("/api/feedback", json={}).status_code == 401
        tok = client.post("/api/session", json={"customer_id": "CUST-1"}).json()["token"]

        r1 = client.post(
            "/api/feedback",
            headers={"Authorization": f"Bearer {tok}"},
            json={"message_id": "msg-api-1", "conversation_id": "c1", "rating": "up"},
        )
        assert r1.status_code == 200 and r1.json()["created"] is True

        r2 = client.post(
            "/api/feedback",
            headers={"Authorization": f"Bearer {tok}"},
            json={"message_id": "msg-api-1", "conversation_id": "c1", "rating": "up"},
        )
        assert r2.status_code == 200 and r2.json()["created"] is False

        # Enqueue and label a sampled review via agent API
        ev = store.record_turn_event(
            conversation_id="c1",
            customer_id="CUST-1",
            intent="policy_question",
            gate_score=0.18,
            question_text="What is the return policy?",
            answer_text="30 days [1].",
        )
        rev = store.enqueue_review(ev)
        agent_headers = {"Authorization": "Bearer agent-secret"}
        listed = client.get("/api/agent/reviews?status=pending", headers=agent_headers)
        assert listed.status_code == 200 and len(listed.json()) == 1

        labeled = client.post(
            f"/api/agent/reviews/{rev.id}/label",
            headers=agent_headers,
            json={
                "reviewer_id": "agent-1",
                "rubric_label": "should_have_handed_off",
                "note": "Answer missed accessory exclusions.",
            },
        )
        assert labeled.status_code == 200
        assert labeled.json()["status"] == "reviewed"

    cands = export_review_candidates(store.list_reviews(status="reviewed"))
    assert len(cands) == 1
    assert cands[0]["answerable"] is False
    assert cands[0]["reviewed"] is False
    store.close()


def test_stratified_sampling_oversamples_near_threshold_and_intents() -> None:
    t0 = datetime(2026, 11, 16, 10, 0, tzinfo=UTC)
    events: list[TurnEventRecord] = []
    # 10 near-threshold turns (score 0.16..0.22 around threshold 0.15)
    for i in range(10):
        events.append(
            TurnEventRecord(
                id=f"near-{i}",
                conversation_id=f"c-near-{i}",
                customer_id="C1",
                intent="policy_question" if i % 2 == 0 else "product_question",
                gate_score=0.16 + (i % 5) * 0.01,
                created_at=t0 + timedelta(minutes=i),
            )
        )
    # 50 high-confidence turns across 3 intents
    for i in range(50):
        events.append(
            TurnEventRecord(
                id=f"high-{i}",
                conversation_id=f"c-high-{i}",
                customer_id="C1",
                intent=["policy_question", "product_question", "order_status"][i % 3],
                gate_score=0.80,
                created_at=t0 + timedelta(minutes=20 + i),
            )
        )
    sampled = sample_for_review(
        events,
        gate_threshold=0.15,
        sample_size=12,
        near_band=0.10,
        near_weight=0.50,
        seed=7,
    )
    assert len(sampled) == 12
    near_count = sum(1 for e in sampled if e.id.startswith("near-"))
    assert near_count == 6  # 50% of sample despite only 10/60 (16.7%) of population
    assert len({e.intent for e in sampled}) == 3


def test_online_citation_validity_check() -> None:
    assert check_citation_validity("Returns take 30 days [1].", [{"n": 1}]) is True
    assert check_citation_validity("Returns take 30 days [2].", [{"n": 1}]) is False
    assert check_citation_validity("Hello, how can I help?", []) is None


def test_simulated_week_replay_catches_day5_shift(tmp_path: Path) -> None:
    drift_md = tmp_path / "drift.md"
    gaps_md = tmp_path / "doc_gaps.md"
    breaches, kb_gaps = run_simulated_week(
        seed=32,
        turns_per_day=30,
        drift_report_path=drift_md,
        doc_gaps_path=gaps_md,
    )
    assert breaches >= 4
    assert kb_gaps > 0
    assert "SIMULATED WEEK REPLAY" in drift_md.read_text(encoding="utf-8")
    assert "policy_question" in gaps_md.read_text(encoding="utf-8")
