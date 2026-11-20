"""Shared fixtures. Unit tests are offline: no network, no Milvus, no real LLM."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from support_agent.config import Settings, get_settings
from support_agent.orders.seed import seed_orders
from support_agent.orders.service import OrderService


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Each test sees settings rebuilt from the current env."""
    monkeypatch.setenv("ENV", "local")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def seeded(tmp_path: Path) -> tuple[Settings, OrderService]:
    settings = Settings()
    # Always a temporary SQLite file: an earlier fixture (postgres_database) may have set
    # ENV=dev, and the dev backend would point at the developer's real DATABASE_URL.
    settings.db.backend = "sqlite"
    settings.orders.db_path = str(tmp_path / "orders.sqlite")
    settings.orders.n_orders = 30
    settings.orders.n_customers = 4
    settings.data.processed_dir = str(tmp_path / "processed")
    seed_orders(settings)
    return settings, OrderService(settings=settings.orders, platform=settings)


@pytest.fixture
def postgres_database(monkeypatch: pytest.MonkeyPatch):
    from support_agent.db.scratch import scratch_database

    monkeypatch.setenv("ENV", "dev")
    settings = Settings()
    with scratch_database(settings) as url:
        yield settings, url
