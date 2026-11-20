"""Concurrent readiness probes with independently bounded response times."""

import asyncio
import logging
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass, field

from anyio import create_task_group, fail_after, to_thread
from sqlalchemy import inspect, literal, select

from support_agent.api.schemas import CheckName, CheckState, ReadyResponse
from support_agent.config import Settings
from support_agent.db.engine import make_engine, postgres_url
from support_agent.db.migrate import CHECKPOINT_TABLES, migration_at_head
from support_agent.graph.postgres import checkpoint_migrations_at_head
from support_agent.infra.redis import NullRedis, RedisStore
from support_agent.infra.settings import ReadinessSettings
from support_agent.orders.service import OrderService
from support_agent.orders.tables import metadata

logger = logging.getLogger(__name__)
Probe = Callable[[], bool]


@dataclass
class ReadinessChecks:
    postgres: Probe | None = None
    migrations: Probe | None = None
    redis: Probe | None = None
    milvus: Probe | None = None
    _running: dict[CheckName, asyncio.Task[bool]] = field(default_factory=dict, init=False)

    async def check(self, name: CheckName, probe: Probe, timeout_s: float) -> bool:
        task = self._running.get(name)
        if task is None or task.done():
            task = asyncio.create_task(_probe(name, probe))
            self._running[name] = task
        try:
            with fail_after(timeout_s):
                # Keep a timed-out worker shared until its actual I/O finishes.
                return await asyncio.shield(task)
        except TimeoutError:
            logger.warning("Readiness check %s failed: TimeoutError", name)
            return False


async def _probe(name: CheckName, probe: Probe) -> bool:
    try:
        return await to_thread.run_sync(probe, abandon_on_cancel=True)
    except Exception as error:
        logger.warning("Readiness check %s failed: %s", name, type(error).__name__)
        return False


def build_redis(settings: Settings) -> RedisStore | NullRedis:
    if settings.redis.backend == "null":
        return NullRedis()
    if settings.redis_url is None:
        raise ValueError("Redis requires REDIS_URL")
    return RedisStore(settings.redis_url.get_secret_value(), settings.redis)


def _down() -> bool:
    return False


def build_readiness(
    settings: Settings, orders: OrderService, milvus: Probe, resources: ExitStack
) -> ReadinessChecks:
    checks = ReadinessChecks(milvus=milvus if settings.milvus.uri else _down)
    if settings.db.backend == "postgres" or settings.graph.checkpoint_backend == "postgres":
        if settings.db.backend == "postgres":
            engine = orders.repository.engine
        else:
            engine = make_engine(postgres_url(settings), settings.db)
            resources.callback(engine.dispose)

        def ping_database() -> bool:
            with engine.connect() as connection:
                return connection.execute(select(literal(1))).scalar_one() == 1

        def check_migrations() -> bool:
            with engine.connect() as connection:
                current_tables = set(inspect(connection).get_table_names())
                return (
                    current_tables >= metadata.tables.keys()
                    and current_tables >= CHECKPOINT_TABLES
                    and migration_at_head(connection)
                    and checkpoint_migrations_at_head(connection)
                )

        checks.postgres = ping_database
        checks.migrations = check_migrations

    try:
        store = build_redis(settings)
    except (TypeError, ValueError) as error:
        logger.warning("Redis readiness configuration failed: %s", type(error).__name__)
        checks.redis = _down
    else:
        if isinstance(store, RedisStore):
            resources.callback(store.close)
            checks.redis = store.ping
    return checks


async def readiness(checks: ReadinessChecks, settings: ReadinessSettings) -> ReadyResponse:
    probes: dict[CheckName, tuple[Probe | None, float]] = {
        "postgres": (checks.postgres, settings.postgres_timeout_s),
        "migrations": (checks.migrations, settings.migrations_timeout_s),
        "redis": (checks.redis, settings.redis_timeout_s),
        "milvus": (checks.milvus, settings.milvus_timeout_s),
    }
    results: dict[CheckName, CheckState] = {}

    async def run(name: CheckName, probe: Probe | None, timeout_s: float) -> None:
        if probe is None:
            results[name] = "disabled"
            return
        ok = await checks.check(name, probe, timeout_s)
        results[name] = "ok" if ok else "down"

    async with create_task_group() as group:
        for name, (probe, timeout_s) in probes.items():
            group.start_soon(run, name, probe, timeout_s)
    return ReadyResponse(status="down" if "down" in results.values() else "ok", checks=results)
