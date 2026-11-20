"""Deterministic fault injection at the dependency call boundaries."""

from random import Random
from threading import Lock
from typing import Literal

from support_agent.reliability.errors import InjectedRateLimit, InjectedTimeout
from support_agent.reliability.guards import Dependency
from support_agent.reliability.settings import ChaosSettings


class ChaosInjector:
    def __init__(self, settings: ChaosSettings) -> None:
        self._settings = settings
        self._rng = Random(settings.seed)
        self._lock = Lock()

    def _draw(self) -> float:
        with self._lock:
            return self._rng.random()

    def llm(self, call_site: str) -> Literal["garbage"] | None:
        cfg = self._settings
        if not cfg.enabled:
            return None
        draw = self._draw()
        if draw < cfg.llm_timeout_rate:
            raise InjectedTimeout(f"Injected model timeout: {call_site}")
        if draw < cfg.llm_timeout_rate + cfg.llm_rate_limit_rate:
            raise InjectedRateLimit(f"Injected model rate limit: {call_site}")
        if draw < cfg.llm_timeout_rate + cfg.llm_rate_limit_rate + cfg.llm_garbage_rate:
            return "garbage"
        return None

    def dependency(self, name: Dependency) -> None:
        cfg = self._settings
        if not cfg.enabled:
            return
        rate = {
            "reranker": cfg.rerank_down_rate,
            "milvus": cfg.milvus_down_rate,
            "orders_db": cfg.orders_down_rate,
        }[name]
        if self._draw() < rate:
            raise InjectedTimeout(f"Injected dependency timeout: {name}")
