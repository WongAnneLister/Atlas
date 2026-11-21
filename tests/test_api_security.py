"""Signed demo sessions and HTTP request limits through the in-process API."""

import pytest

from support_agent.infra.redis import NullRedis
from test_api import QUESTION, REQUEST, client


@pytest.mark.parametrize("endpoint", ["chat", "resume"])
@pytest.mark.parametrize("authorization", [None, "Basic unrelated", "Bearer invalid"])
async def test_turns_require_session_token(seeded, endpoint, authorization) -> None:
    async with client(seeded, customer_id=None) as api:
        payload = QUESTION if endpoint == "chat" else {**REQUEST, "value": "none"}
        headers = {"Authorization": authorization} if authorization else {}
        response = await api.post(f"/api/{endpoint}", json=payload, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_session_is_issued_only_for_listed_demo_customers(seeded) -> None:
    async with client(seeded, customer_id=None) as api:
        listed = (await api.get("/api/customers")).json()
        assert {customer["customer_id"] for customer in listed} == {"CUST-0001", "CUST-0002"}
        allowed = await api.post("/api/session", json={"customer_id": "CUST-0001"})
        assert allowed.status_code == 200
        assert allowed.json()["token"]
        assert allowed.headers["cache-control"] == "no-store"
        for unknown in ["CUST-0003", "unknown"]:
            response = await api.post("/api/session", json={"customer_id": unknown})
            assert response.status_code == 403


async def test_expired_or_changed_signature_is_unauthorized(seeded, monkeypatch) -> None:
    from support_agent.api import security

    settings, _ = seeded
    now = 100.0
    monkeypatch.setattr(security, "time", lambda: now)
    monkeypatch.setenv("SESSION_SECRET", "synthetic-test-signing-secret")
    async with client(seeded, customer_id=None) as api:
        response = await api.post("/api/session", json={"customer_id": "CUST-0001"})
        token = response.json()["token"]
        payload, signature = token.split(".")
        tampered = payload + "." + ("A" if signature[0] != "A" else "B") + signature[1:]
        for invalid in [tampered, "invalid.!", "é.abcd"]:
            with pytest.raises(security.InvalidSession):
                security.SessionTokens.from_environment(settings.api.session).verify(invalid)
        assert (
            await api.post(
                "/api/resume",
                json={**REQUEST, "value": "none"},
                headers={"Authorization": f"Bearer {token}"},
            )
        ).status_code == 409
        now += settings.api.session.ttl_s
        response = await api.post(
            "/api/chat", json=QUESTION, headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 401


async def test_chat_ignores_legacy_body_customer(seeded) -> None:
    async with client(seeded) as api:
        response = await api.post("/api/chat", json={**QUESTION, "customer_id": "body-only"})
    assert response.status_code == 200


@pytest.mark.parametrize("streamed", [False, True])
async def test_body_size_limit_applies_without_trusting_content_length(seeded, streamed) -> None:
    settings, _ = seeded
    settings.api.max_body_bytes = 100

    async def large_body():
        yield b"x" * 50
        yield b"x" * 51
        pytest.fail("Oversized body was drained")

    content = large_body() if streamed else b"x" * 101
    async with client(seeded) as api:
        response = await api.post("/api/chat", content=content)
    assert response.status_code == 413
    assert response.json() == {"detail": "Request body exceeds the configured size limit"}
    assert response.headers["x-trace-id"]


async def test_customer_limit_uses_token_identity_and_resets_next_window(
    seeded, monkeypatch
) -> None:
    from support_agent.api import security

    settings, _ = seeded
    settings.api.rate_limit.per_customer = 1
    settings.api.rate_limit.window_s = 60
    now = 65.0
    monkeypatch.setattr(security, "time", lambda: now)
    async with client(seeded) as api:
        for body_id, expected in [("CUST-0001", 409), ("CUST-0002", 429)]:
            response = await api.post(
                "/api/resume", json={**REQUEST, "value": "none", "customer_id": body_id}
            )
            assert response.status_code == expected
        assert response.headers["retry-after"] == "55"
        now = 120.0
        response = await api.post("/api/resume", json={**REQUEST, "value": "none"})
        assert response.status_code == 409


async def test_ip_limit_uses_transport_address_and_covers_sessions(seeded) -> None:
    settings, _ = seeded
    settings.api.rate_limit.per_ip = 2
    async with client(seeded, customer_id=None) as api:
        for customer_id in ["CUST-0001", "CUST-0002"]:
            response = await api.post("/api/session", json={"customer_id": customer_id})
            assert response.status_code == 200
        response = await api.post(
            "/api/session",
            json={"customer_id": "CUST-0001"},
            headers={"X-Forwarded-For": "192.0.2.90"},
        )
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0


async def test_configured_rate_store_failure_stops_before_graph(seeded) -> None:
    class UnavailableStore(NullRedis):
        def incr(self, key: str, ttl_s: int) -> int:
            raise ConnectionError("private store connection detail")

    settings, _ = seeded
    settings.redis.backend = "redis"
    async with client(seeded, customer_id=None, lock_store=UnavailableStore()) as api:
        response = await api.post("/api/session", json={"customer_id": "CUST-0001"})
    assert response.status_code == 503
    assert response.json() == {"detail": "Rate limit unavailable"}


def test_session_signatures_are_shared_only_with_same_secret(monkeypatch) -> None:
    from support_agent.api.security import InvalidSession, SessionTokens
    from support_agent.config import Settings

    settings = Settings().api.session
    monkeypatch.setenv("SESSION_SECRET", "synthetic-secret-one")
    token = SessionTokens.from_environment(settings).issue("CUST-0001")
    assert SessionTokens.from_environment(settings).verify(token) == "CUST-0001"
    monkeypatch.setenv("SESSION_SECRET", "synthetic-secret-two")
    with pytest.raises(InvalidSession):
        SessionTokens.from_environment(settings).verify(token)


@pytest.mark.parametrize("declared", [0, 5])
async def test_body_limit_accepts_exact_size_and_rejects_understated_header(
    seeded, declared
) -> None:
    settings, _ = seeded
    # An empty JSON object requires 2 bytes and fails schema validation after size checking.
    settings.api.max_body_bytes = 2
    async with client(seeded, customer_id=None) as api:
        exact = await api.post("/api/session", content=b"{}")
        assert exact.status_code == 422
        response = await api.post(
            "/api/session", content=b"{}\n", headers={"Content-Length": str(declared)}
        )
    assert response.status_code == 413


async def test_token_auth_respects_application_root_path(seeded) -> None:
    async with client(seeded, root_path="/demo") as api:
        response = await api.post("/api/resume", json={**REQUEST, "value": "none"})
        assert response.status_code == 409
        response = await api.post(
            "/api/resume",
            json={**REQUEST, "value": "none"},
            headers={"Authorization": "Bearer bad"},
        )
    assert response.status_code == 401


def test_rate_limits_share_redis_counter_across_workers(monkeypatch) -> None:
    from support_agent.api import security
    from support_agent.config import Settings

    settings = Settings().api.rate_limit
    settings.per_customer = 1
    settings.window_s = 60
    monkeypatch.setattr(security, "time", lambda: 118.0)
    store = NullRedis()
    first = security.RateLimits(settings, store, shared=True)
    second = security.RateLimits(settings, store, shared=True)
    assert first.retry_after("192.0.2.20", "CUST-0001") is None
    assert second.retry_after("192.0.2.21", "CUST-0001") == 2
    assert second.retry_after("192.0.2.20", "CUST-0002") is None


async def test_signed_token_for_customer_removed_from_demo_list_is_refused(seeded) -> None:
    settings, _ = seeded
    async with client(seeded, customer_id="CUST-0002") as api:
        settings.api.demo_customer_limit = 1
        response = await api.post("/api/resume", json={**REQUEST, "value": "none"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
