"""Typed reliability controls and the dependency budgets for a locked turn."""

from typing import TYPE_CHECKING, Annotated, Self

from pydantic import BaseModel, Field, StringConstraints, model_validator

if TYPE_CHECKING:
    from support_agent.config import Settings

Seconds = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Rate = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
ModelName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class FallbackSettings(BaseModel):
    fast: list[ModelName] = Field(default_factory=list)
    main: list[ModelName] = Field(default_factory=list)


class TimeoutSettings(BaseModel):
    input_guard: Seconds
    rewrite: Seconds
    plan: Seconds
    classify: Seconds
    answer: Seconds
    decide: Seconds
    order_extract: Seconds
    grounding: Seconds
    verify: Seconds
    complaint: Seconds
    tools: Seconds
    summarise: Seconds = 20
    extract_facts: Seconds = 15
    rerank: Seconds
    orders_db: Seconds

    def llm_max_s(self) -> float:
        return max(
            self.input_guard,
            self.rewrite,
            self.plan,
            self.classify,
            self.answer,
            self.decide,
            self.order_extract,
            self.grounding,
            self.verify,
            self.complaint,
            self.tools,
        )


class RetrySettings(BaseModel):
    max_attempts: int = Field(ge=1)
    base_delay_s: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    max_delay_s: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    jitter_ratio: Rate
    budget_s: Seconds

    @model_validator(mode="after")
    def _delay_range(self) -> Self:
        if self.base_delay_s > self.max_delay_s:
            raise ValueError("base_delay_s must not exceed max_delay_s")
        return self


class CircuitSettings(BaseModel):
    failure_threshold: int = Field(gt=0)
    cool_down_s: Seconds
    half_open_max_calls: int = Field(gt=0)


class LockSettings(BaseModel):
    conversation_ttl_s: int = Field(gt=0)
    renew_interval_s: Seconds


class MetricsSettings(BaseModel):
    latency_buckets_s: list[Seconds] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_buckets(self) -> Self:
        if self.latency_buckets_s != sorted(set(self.latency_buckets_s)):
            raise ValueError("latency_buckets_s must be strictly increasing")
        return self


class ReliabilitySettings(BaseModel):
    timeouts_s: TimeoutSettings
    retry: RetrySettings
    circuit: CircuitSettings
    locks: LockSettings
    metrics: MetricsSettings
    repair_error_max_chars: int = Field(gt=0)
    llm_max_in_flight: int = Field(default=16, gt=0)


class ChaosSettings(BaseModel):
    enabled: bool
    seed: int
    llm_timeout_rate: Rate
    llm_rate_limit_rate: Rate
    llm_garbage_rate: Rate
    rerank_down_rate: Rate
    milvus_down_rate: Rate
    orders_down_rate: Rate

    @model_validator(mode="after")
    def _llm_fault_budget(self) -> Self:
        if self.llm_timeout_rate + self.llm_rate_limit_rate + self.llm_garbage_rate > 1:
            raise ValueError("Combined LLM fault rates must not exceed 1")
        return self


def validate_reliability(settings: "Settings") -> None:
    reliability = settings.reliability
    timeouts = reliability.timeouts_s
    if timeouts.llm_max_s() > settings.llm.timeout_s:
        raise ValueError("LLM call site timeouts must not exceed llm.timeout_s")
    if settings.milvus.timeout_s > reliability.retry.budget_s:
        raise ValueError("milvus.timeout_s must not exceed reliability.retry.budget_s")
    if max(timeouts.llm_max_s(), timeouts.rerank, timeouts.orders_db) > reliability.retry.budget_s:
        raise ValueError("Call site timeouts must not exceed reliability.retry.budget_s")
    if (
        reliability.locks.renew_interval_s
        + settings.redis.connect_timeout_s
        + settings.redis.socket_timeout_s
        >= reliability.locks.conversation_ttl_s
    ):
        raise ValueError("conversation_ttl_s must exceed renew_interval_s plus the Redis timeouts")
