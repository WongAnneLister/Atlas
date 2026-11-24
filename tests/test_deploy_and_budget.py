"""Offline unit tests for Commit 34 (daily spend cap, Docker/Compose, release workflow)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml
from fastapi.testclient import TestClient

from support_agent.api.app import create_app
from support_agent.api.budget import DailySpendCap
from support_agent.api.deps import ApiDeps
from support_agent.config import REPO_ROOT, get_settings
from support_agent.graph.deps import GraphDeps
from support_agent.orders.models import CustomerSummary


def test_daily_spend_cap_tracks_and_rolls_over_utc_day() -> None:
    current_day = [date(2026, 11, 24)]
    cap = DailySpendCap(1.00, today_fn=lambda: current_day[0])
    assert cap.enabled is True
    assert cap.exceeded() is False
    assert cap.remaining() == 1.00

    cap.record(0.60)
    assert cap.exceeded() is False
    assert cap.spent_today() == 0.60

    cap.record(0.50)
    assert cap.exceeded() is True
    assert cap.remaining() == 0.0

    # Next UTC day resets spend to 0
    current_day[0] = date(2026, 11, 25)
    assert cap.exceeded() is False
    assert cap.spent_today() == 0.0


def test_api_returns_demo_budget_handoff_when_spend_cap_exceeded() -> None:
    class _FakeOrders:
        def list_customers(self, limit: int = 10) -> list[CustomerSummary]:
            return [CustomerSummary(customer_id="CUST-1", name="Alice", email="a@example.com")]

    settings = get_settings().model_copy(deep=True)
    settings.api.demo_budget.daily_spend_cap_usd = 0.50
    api_deps = ApiDeps(
        settings=settings,
        graph_deps=GraphDeps(settings=settings),
        order_service=_FakeOrders(),  # type: ignore[arg-type]
        milvus_check=lambda: True,
        warmup=False,
    )
    app = create_app(api_deps)
    app.state.spend_cap.record(0.75)  # cross cap

    with TestClient(app) as client:
        tok = client.post("/api/session", json={"customer_id": "CUST-1"}).json()["token"]
        with client.stream(
            "POST",
            "/api/chat",
            headers={"Authorization": f"Bearer {tok}"},
            json={"conversation_id": "cap-1", "message": "What is the return policy?"},
        ) as resp:
            assert resp.status_code == 200
            body = "".join(resp.iter_text())
        assert "demo_budget_reached" in body
        assert "daily LLM budget" in body


def test_production_dockerfile_compose_and_release_workflow() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "USER atlas" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "DEEPSEEK_API_KEY" not in dockerfile

    compose: dict[str, Any] = yaml.safe_load(
        (REPO_ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    )
    services = compose["services"]
    for name in ("caddy", "api", "postgres", "redis", "milvus"):
        assert name in services
    assert "healthcheck" in services["api"]
    assert "volumes" in compose and "model_cache" in compose["volumes"]

    workflow_path: Path = REPO_ROOT / ".github" / "workflows" / "release.yml"
    wf: dict[str, Any] = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    # PyYAML parses `on:` as boolean True in YAML 1.1
    triggers = wf.get("on") or wf.get(True)
    assert "workflow_dispatch" in triggers
    assert "push" in triggers and "v*" in triggers["push"]["tags"]
    assert "verify-and-build" in wf["jobs"]
    assert "eval-gate" in wf["jobs"]
    assert "deploy" in wf["jobs"]
    deploy_steps = str(wf["jobs"]["deploy"]["steps"])
    assert "skipping remote deploy" in deploy_steps
