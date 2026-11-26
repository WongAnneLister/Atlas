"""The agent console must stay closed unless a private token is configured."""

import pytest
from fastapi.testclient import TestClient

from support_agent.api.app import ApiDeps, create_app
from support_agent.api.security import PUBLIC_AGENT_TOKEN, agent_token
from support_agent.config import get_settings
from support_agent.graph.deps import GraphDeps
from support_agent.orders.models import CustomerSummary


class _Orders:
    def list_customers(self, limit: int = 10) -> list[CustomerSummary]:
        return [CustomerSummary(customer_id="CUST-1", name="Alice Example", email="a@example.com")]


def _client(configured: str | None) -> TestClient:
    settings = get_settings().model_copy(deep=True)
    settings.handoff.demo_agent_token = configured
    settings.graph.checkpoint_backend = "memory"
    deps = ApiDeps(
        settings=settings,
        graph_deps=GraphDeps(settings=settings),
        order_service=_Orders(),  # type: ignore[arg-type]
        milvus_check=lambda: True,
        warmup=False,
    )
    return TestClient(create_app(deps))


def test_shipped_defaults_do_not_open_the_agent_console(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_TOKEN", raising=False)
    assert get_settings().handoff.demo_agent_token is None
    with _client(get_settings().handoff.demo_agent_token) as client:
        response = client.get(
            "/api/agent/reviews", headers={"Authorization": f"Bearer {PUBLIC_AGENT_TOKEN}"}
        )
    assert response.status_code == 503


@pytest.mark.parametrize("source", ["env", "config"])
def test_public_token_is_refused_wherever_it_is_set(
    monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    monkeypatch.delenv("AGENT_TOKEN", raising=False)
    if source == "env":
        monkeypatch.setenv("AGENT_TOKEN", PUBLIC_AGENT_TOKEN)
        assert agent_token(None) is None
    else:
        assert agent_token(PUBLIC_AGENT_TOKEN) is None


def test_private_env_token_opens_the_console_and_wins_over_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_TOKEN", "private-env-token")
    assert agent_token("config-token") == "private-env-token"
    with _client("config-token") as client:
        wrong = client.get("/api/agent/reviews", headers={"Authorization": "Bearer config-token"})
        right = client.get(
            "/api/agent/reviews", headers={"Authorization": "Bearer private-env-token"}
        )
    assert wrong.status_code == 401
    assert right.status_code != 401 and right.status_code != 503
