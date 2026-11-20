"""Retry transient failures of operations with an explicit idempotency contract."""

from collections.abc import Callable
from random import Random, uniform
from time import monotonic
from time import sleep as sleep_seconds
from typing import TypeVar

from support_agent.reliability.errors import CircuitOpen, RetryBudgetExceeded, is_retryable
from support_agent.reliability.settings import RetrySettings

T = TypeVar("T")


def retry_call(
    fn: Callable[[float], T],
    *,
    policy: RetrySettings,
    is_idempotent: bool,
    sleep: Callable[[float], None] = sleep_seconds,
    clock: Callable[[], float] = monotonic,
    rng: Random | None = None,
    on_retry: Callable[[], None] | None = None,
    deadline: float | None = None,
) -> T:
    """Pass remaining seconds to each attempt, which must enforce that deadline."""
    if not is_idempotent and policy.max_attempts > 1:
        raise ValueError("Retries require an idempotent operation")
    budget_end = clock() + policy.budget_s
    if deadline is not None:
        budget_end = min(deadline, budget_end)
    sample = rng.uniform if rng is not None else uniform
    delay = policy.base_delay_s
    for attempt in range(policy.max_attempts):
        remaining = budget_end - clock()
        if remaining <= 0:
            raise RetryBudgetExceeded("Dependency retry budget exhausted")
        if attempt and on_retry is not None:
            on_retry()
        try:
            result = fn(remaining)
        except Exception as error:
            if (
                attempt + 1 == policy.max_attempts
                or isinstance(error, CircuitOpen)
                or not is_retryable(error)
            ):
                raise
            jitter = delay * policy.jitter_ratio
            pause = min(policy.max_delay_s, delay + sample(-jitter, jitter))
            if pause >= budget_end - clock():
                raise
            if pause:
                sleep(pause)
            delay = min(policy.max_delay_s, delay * 2)
        else:
            if clock() > budget_end:
                raise RetryBudgetExceeded("Dependency operation exceeded its retry budget")
            return result
    raise AssertionError("Retry settings must allow at least one attempt")
