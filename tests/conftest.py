"""Shared fixtures. Unit tests are offline: no network, no Milvus, no real LLM."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from support_agent.config import get_settings


@pytest.fixture(autouse=True)
def _fresh_settings() -> Iterator[None]:
    """Each test sees settings rebuilt from the current env."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
