"""Locust load test for Atlas API with weighted traffic mix and SSE streaming.

Run via:
  make loadtest PROFILE=steady USERS=20 DURATION=60s HOST=http://127.0.0.1:8000
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

from loadtest.workload import (
    ATTACK_PROMPTS,
    CHITCHAT_PROMPTS,
    ORDER_PROMPTS,
    POLICY_PROMPTS,
    REFUND_PROMPTS,
    TASK_WEIGHTS,
)

__all__ = [
    "ATTACK_PROMPTS",
    "CHITCHAT_PROMPTS",
    "ORDER_PROMPTS",
    "POLICY_PROMPTS",
    "REFUND_PROMPTS",
    "TASK_WEIGHTS",
    "AtlasChatUser",
    "ProfiledLoadShape",
]

try:
    from locust import HttpUser, LoadTestShape, between, events, task
except ImportError:  # pragma: no cover - optional loadtest extra
    HttpUser = object  # type: ignore[misc, assignment]
    LoadTestShape = object  # type: ignore[misc, assignment]

    def between(a: float, b: float) -> Any:
        return (a, b)

    def task(weight: int = 1) -> Any:
        def wrap(fn: Any) -> Any:
            return fn

        return wrap

    events = None  # type: ignore[assignment]


class AtlasChatUser(HttpUser):
    wait_time = between(0.5, 2.0)

    def on_start(self) -> None:
        self.customer_id = "CUST-0001"
        self.token = ""
        resp = self.client.get("/api/customers", name="GET /api/customers")
        if resp.ok:
            rows = resp.json()
            if rows:
                self.customer_id = rows[0]["customer_id"]
        sess = self.client.post(
            "/api/session",
            json={"customer_id": self.customer_id},
            name="POST /api/session",
        )
        if sess.ok:
            self.token = sess.json().get("token", "")

    def _run_sse(
        self,
        endpoint: str,
        payload: dict[str, Any],
        *,
        label: str,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        ttft_ms: float | None = None
        interrupt_orders: list[dict[str, Any]] = []
        headers = {"Authorization": f"Bearer {self.token}"}
        with self.client.post(
            endpoint,
            json=payload,
            headers=headers,
            stream=True,
            name=f"POST {endpoint} [{label}]",
            catch_response=True,
        ) as resp:
            if resp.status_code in {429, 503}:
                resp.failure(f"backpressure {resp.status_code}")
                return {"status": resp.status_code, "ttft_ms": None, "orders": []}
            if not resp.ok:
                resp.failure(f"HTTP {resp.status_code}")
                return {"status": resp.status_code, "ttft_ms": None, "orders": []}
            event_name = ""
            for raw_line in resp.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                if raw_line.startswith("event: "):
                    event_name = raw_line[7:].strip()
                elif raw_line.startswith("data: "):
                    if ttft_ms is None and event_name in {"token", "handoff", "interrupt"}:
                        ttft_ms = (time.perf_counter() - t0) * 1000.0
                    if event_name == "interrupt":
                        try:
                            data = json.loads(raw_line[6:])
                            interrupt_orders = list(data.get("orders") or [])
                        except Exception:
                            pass
            resp.success()
        if events is not None and ttft_ms is not None:
            events.request.fire(
                request_type="SSE_TTFT",
                name=f"TTFT [{label}]",
                response_time=ttft_ms,
                response_length=0,
                exception=None,
            )
        return {"status": 200, "ttft_ms": ttft_ms, "orders": interrupt_orders}

    @task(50)
    def policy_question(self) -> None:
        conv_id = f"lt-pol-{uuid.uuid4().hex[:10]}"
        prompt = POLICY_PROMPTS[hash(conv_id) % len(POLICY_PROMPTS)]
        self._run_sse(
            "/api/chat", {"conversation_id": conv_id, "message": prompt}, label="policy_q"
        )

    @task(20)
    def order_status(self) -> None:
        conv_id = f"lt-ord-{uuid.uuid4().hex[:10]}"
        prompt = ORDER_PROMPTS[hash(conv_id) % len(ORDER_PROMPTS)]
        self._run_sse(
            "/api/chat", {"conversation_id": conv_id, "message": prompt}, label="order_status"
        )

    @task(15)
    def refund_flow(self) -> None:
        conv_id = f"lt-ref-{uuid.uuid4().hex[:10]}"
        prompt = REFUND_PROMPTS[hash(conv_id) % len(REFUND_PROMPTS)]
        res = self._run_sse(
            "/api/chat", {"conversation_id": conv_id, "message": prompt}, label="refund"
        )
        if res["orders"]:
            order_id = res["orders"][0].get("order_id", "none")
            self._run_sse(
                "/api/resume",
                {"conversation_id": conv_id, "value": order_id},
                label="refund_resume",
            )

    @task(10)
    def chitchat(self) -> None:
        conv_id = f"lt-chi-{uuid.uuid4().hex[:10]}"
        prompt = CHITCHAT_PROMPTS[hash(conv_id) % len(CHITCHAT_PROMPTS)]
        self._run_sse(
            "/api/chat", {"conversation_id": conv_id, "message": prompt}, label="chitchat"
        )

    @task(5)
    def attack(self) -> None:
        conv_id = f"lt-atk-{uuid.uuid4().hex[:10]}"
        self._run_sse(
            "/api/chat",
            {"conversation_id": conv_id, "message": ATTACK_PROMPTS[0]},
            label="attack",
        )


class ProfiledLoadShape(LoadTestShape):
    """Supports LOADTEST_PROFILE = steady | ramp | spike."""

    def tick(self) -> tuple[int, float] | None:
        profile = os.getenv("LOADTEST_PROFILE", "steady").strip().lower()
        target = int(os.getenv("LOADTEST_USERS", "20"))
        duration = int(os.getenv("LOADTEST_DURATION_S", "60"))
        elapsed = self.get_run_time()
        if elapsed >= duration:
            return None
        if profile == "ramp":
            users = max(1, int(target * min(1.0, (elapsed + 1) / max(1, duration * 0.7))))
            return (users, max(1.0, target / 10.0))
        if profile == "spike":
            if duration * 0.3 <= elapsed <= duration * 0.6:
                return (target * 2, float(target))
            return (max(1, target // 2), max(1.0, target / 5.0))
        return (target, max(1.0, target / 5.0))
