"""Offline unit tests for Commit 33 (mock LLM server, backpressure, customer cache, Locust)."""

from __future__ import annotations

import sys
import time

from fastapi.testclient import TestClient
from loadtest.mock_llm import MockLLMConfig, create_mock_llm_app
from loadtest.workload import TASK_WEIGHTS

from support_agent.api.app import create_app
from support_agent.api.backpressure import CustomerAllowlistCache, InFlightLimiter
from support_agent.api.deps import ApiDeps
from support_agent.config import get_settings
from support_agent.graph.deps import GraphDeps
from support_agent.orders.models import CustomerSummary


def test_mock_llm_deterministic_json_and_sse_streaming() -> None:
    app = create_mock_llm_app(MockLLMConfig(base_latency_ms=10.0, tokens_per_sec=1000.0))
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200

        # Non-streaming JSON with timing >= base_latency_ms
        t0 = time.perf_counter()
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "mock-load-llm",
                "messages": [{"role": "user", "content": "What is the return policy?"}],
                "stream": False,
            },
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        assert resp.status_code == 200
        assert elapsed_ms >= 8.0
        body = resp.json()
        assert "30 days" in body["choices"][0]["message"]["content"]

        # Deterministic SSE streaming
        with client.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "model": "mock-load-llm",
                "messages": [{"role": "user", "content": "What is the return policy?"}],
                "stream": True,
            },
        ) as stream_resp:
            assert stream_resp.status_code == 200
            lines = [line for line in stream_resp.iter_lines() if line.startswith("data: ")]
        assert lines[-1] == "data: [DONE]"
        assert len(lines) >= 3


def test_in_flight_limiter_and_api_backpressure_503_retry_after() -> None:
    limiter = InFlightLimiter(max_in_flight=2, retry_after_s=3)
    assert limiter.try_acquire() is True
    assert limiter.try_acquire() is True
    assert limiter.try_acquire() is False
    assert limiter.in_flight == 2
    limiter.release()
    assert limiter.try_acquire() is True
    limiter.release()
    limiter.release()
    assert limiter.in_flight == 0

    # Verify API returns 503 with Retry-After when max_in_flight is exhausted
    class _FakeOrders:
        def list_customers(self, limit: int = 10) -> list[CustomerSummary]:
            return [CustomerSummary(customer_id="CUST-1", name="Alice", email="a@example.com")]

    settings = get_settings().model_copy(deep=True)
    settings.api.concurrency.max_in_flight = 1
    settings.api.concurrency.retry_after_s = 4
    graph_deps = GraphDeps(settings=settings)
    api_deps = ApiDeps(
        settings=settings,
        graph_deps=graph_deps,
        order_service=_FakeOrders(),  # type: ignore[arg-type]
        milvus_check=lambda: True,
        warmup=False,
    )
    app = create_app(api_deps)
    # Saturate the single in-flight slot directly via a slow lock or concurrent request
    with TestClient(app) as client:
        tok = client.post("/api/session", json={"customer_id": "CUST-1"}).json()["token"]
        # Hold the limiter indirectly by testing with a 0-capacity check on a second app
        assert tok

    # Direct HTTP verification: acquire slot via custom lock holder
    from support_agent.api import app as app_mod

    orig = app_mod.InFlightLimiter

    class _PreSaturatedLimiter(InFlightLimiter):
        def __init__(self, max_in_flight: int, retry_after_s: int) -> None:
            super().__init__(max_in_flight, retry_after_s)
            self.try_acquire()  # pre-fill the single slot

    app_mod.InFlightLimiter = _PreSaturatedLimiter  # type: ignore[misc]
    try:
        api_deps2 = ApiDeps(
            settings=settings,
            graph_deps=GraphDeps(settings=settings),
            order_service=_FakeOrders(),  # type: ignore[arg-type]
            milvus_check=lambda: True,
            warmup=False,
        )
        app2 = create_app(api_deps2)
        with TestClient(app2) as client:
            tok = client.post("/api/session", json={"customer_id": "CUST-1"}).json()["token"]
            res = client.post(
                "/api/chat",
                headers={"Authorization": f"Bearer {tok}"},
                json={"conversation_id": "bp-1", "message": "Hello"},
            )
            assert res.status_code == 503
            assert res.headers.get("Retry-After") == "4"
    finally:
        app_mod.InFlightLimiter = orig  # type: ignore[misc]


def test_customer_allowlist_cache_reduces_db_calls() -> None:
    calls = 0

    def loader(limit: int) -> list[CustomerSummary]:
        nonlocal calls
        calls += 1
        return [CustomerSummary(customer_id="CUST-1", name="Alice", email="a@example.com")][:limit]

    cache = CustomerAllowlistCache(loader, ttl_s=10.0)
    assert cache.contains("CUST-1", 8) is True
    assert cache.contains("CUST-1", 8) is True
    assert cache.contains("CUST-999", 8) is False
    assert len(cache.list_customers(8)) == 1
    assert calls == 1
    # Changing limit invalidates cache immediately
    assert len(cache.list_customers(1)) == 1
    assert calls == 2


def test_locust_task_weights_sum_to_100() -> None:
    assert sum(TASK_WEIGHTS.values()) == 100
    assert TASK_WEIGHTS["policy_question"] == 50
    assert TASK_WEIGHTS["attack"] == 5
    # Importing loadtest.workload in pytest must never trigger locust / gevent monkey-patching.
    assert "locust" not in sys.modules
    assert "gevent" not in sys.modules
