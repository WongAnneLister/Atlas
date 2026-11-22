"""Test fixtures must never write to the developer's configured databases."""

from __future__ import annotations

from typing import Any

import pytest

# Port 1 on loopback refuses connections, so any attempt to use Postgres fails loudly.
UNREACHABLE = "postgresql+psycopg://atlas:atlas@127.0.0.1:1/atlas"


@pytest.fixture
def dev_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reproduce what postgres_database does before seeded runs in an integration test."""
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE)


def test_seeded_orders_stay_in_sqlite_when_env_is_dev(dev_environment: None, seeded: Any) -> None:
    settings, service = seeded
    assert settings.db.backend == "sqlite"
    assert service.repository.engine.dialect.name == "sqlite"
    assert len(service.list_customers(10)) == settings.orders.n_customers + 1
