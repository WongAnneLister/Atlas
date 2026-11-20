import threading

import pytest

from test_api import client


async def test_liveness_does_not_touch_dependencies(seeded) -> None:
    def unexpected() -> bool:
        raise AssertionError("Liveness called a dependency")

    async with client(seeded, milvus=unexpected) as api:
        live = await api.get("/api/health/live")
    assert live.status_code == 200
    assert live.json() == {"status": "ok"}


async def test_local_readiness_disables_unused_services(seeded) -> None:
    async with client(seeded) as api:
        ready = await api.get("/api/health/ready")
    assert ready.status_code == 200
    assert ready.json() == {
        "status": "ok",
        "checks": {
            "postgres": "disabled",
            "migrations": "disabled",
            "redis": "disabled",
            "milvus": "ok",
        },
    }


@pytest.mark.parametrize("redis_works", [True, False])
async def test_readiness_reports_separate_failures(seeded, redis_works) -> None:
    from support_agent.api.readiness import ReadinessChecks

    def redis() -> bool:
        if not redis_works:
            raise RuntimeError("This detail must stay out of the response")
        return True

    checks = ReadinessChecks(
        postgres=lambda: True, migrations=lambda: True, redis=redis, milvus=lambda: True
    )
    async with client(seeded, readiness=checks) as api:
        ready = await api.get("/api/health/ready")
    assert ready.status_code == (200 if redis_works else 503)
    assert ready.json()["checks"] == {
        "postgres": "ok",
        "migrations": "ok",
        "redis": "ok" if redis_works else "down",
        "milvus": "ok",
    }
    assert "detail" not in ready.text


async def test_readiness_times_out_independently(seeded) -> None:
    from support_agent.api.readiness import ReadinessChecks

    settings, _ = seeded
    settings.readiness.milvus_timeout_s = 0.05
    redis_ran = threading.Event()
    release = threading.Event()

    def redis() -> bool:
        redis_ran.set()
        return True

    def slow() -> bool:
        return redis_ran.wait(0.5) and release.wait(2)

    checks = ReadinessChecks(milvus=slow, redis=redis)
    try:
        async with client(seeded, readiness=checks) as api:
            ready = await api.get("/api/health/ready")
        assert redis_ran.is_set()
        assert ready.status_code == 503
        assert ready.json()["checks"] == {
            "postgres": "disabled",
            "migrations": "disabled",
            "redis": "ok",
            "milvus": "down",
        }
    finally:
        release.set()


@pytest.mark.integration
async def test_ready_with_real_postgres_and_redis(postgres_database) -> None:
    from pydantic import SecretStr

    from support_agent.db.migrate import upgrade
    from support_agent.graph.postgres import postgres_saver
    from support_agent.orders import OrderService

    settings, url = postgres_database
    settings.database_url = SecretStr(url.render_as_string(hide_password=False))
    service = OrderService(platform=settings)
    try:
        async with client((settings, service)) as api:
            ready = await api.get("/api/health/ready")
            assert ready.status_code == 503
            assert ready.json()["checks"] == {
                "postgres": "ok",
                "migrations": "down",
                "redis": "ok",
                "milvus": "ok",
            }
            upgrade(service.repository.engine)
            assert (await api.get("/api/health/ready")).json()["checks"]["migrations"] == "down"
            with postgres_saver(settings) as saver:
                # The first four migrations create every checkpoint table.
                with service.repository.engine.begin() as connection:
                    for version, ddl in enumerate(saver.MIGRATIONS[:4]):
                        connection.exec_driver_sql(ddl)
                        connection.exec_driver_sql(
                            "INSERT INTO checkpoint_migrations (v) VALUES (%s)", (version,)
                        )
                assert (await api.get("/api/health/ready")).json()["checks"]["migrations"] == "down"
                saver.setup()
            ready = await api.get("/api/health/ready")
            assert ready.status_code == 200
            assert set(ready.json()["checks"].values()) == {"ok"}
    finally:
        service.close()


async def test_timed_out_readiness_reuses_the_running_probe(seeded) -> None:
    from support_agent.api.readiness import ReadinessChecks

    settings, _ = seeded
    settings.readiness.milvus_timeout_s = 0.05
    release = threading.Event()
    calls = 0

    def slow() -> bool:
        nonlocal calls
        calls += 1
        return release.wait(2)

    checks = ReadinessChecks(milvus=slow)
    try:
        async with client(seeded, readiness=checks) as api:
            assert (await api.get("/api/health/ready")).status_code == 503
            assert (await api.get("/api/health/ready")).status_code == 503
            assert calls == 1
    finally:
        release.set()
