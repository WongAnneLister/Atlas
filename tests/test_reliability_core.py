from concurrent.futures import ThreadPoolExecutor
from random import Random
from threading import Event

import httpx
import pytest

from support_agent.reliability.circuit import CircuitRegistry, CircuitState
from support_agent.reliability.errors import (
    CircuitOpen,
    InjectedRateLimit,
    InjectedTimeout,
    RetryBudgetExceeded,
    is_retryable,
)
from support_agent.reliability.retry import retry_call
from support_agent.reliability.settings import CircuitSettings, RetrySettings


class ManualClock:
    now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def policy(*, attempts: int = 5, budget: float = 9, jitter: float = 0) -> RetrySettings:
    return RetrySettings(
        max_attempts=attempts,
        base_delay_s=1,
        max_delay_s=2,
        jitter_ratio=jitter,
        budget_s=budget,
    )


@pytest.mark.parametrize(
    ("status", "expected"), [(400, False), (401, False), (429, True), (503, True)]
)
def test_http_status_classifies_failure(status: int, expected: bool) -> None:
    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(status, request=request)
    error = httpx.HTTPStatusError("test", request=request, response=response)
    assert is_retryable(error) is expected


class ProviderError(Exception):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ProviderError(502), True),
        (ProviderError(422), False),
        (ConnectionError(), True),
        (httpx.ConnectError("test"), True),
        (httpx.ReadTimeout("test"), True),
        (httpx.LocalProtocolError("test"), False),
        (CircuitOpen("test"), True),
        (InjectedRateLimit(), True),
        (InjectedTimeout(), True),
        (ValueError(), False),
        (LookupError(), False),
    ],
)
def test_retryable_error_classes(error: Exception, expected: bool) -> None:
    assert is_retryable(error) is expected


def test_retries_use_capped_backoff_and_give_attempts_the_remaining_budget() -> None:
    seconds = ManualClock()
    budgets: list[float] = []
    retry_times: list[float] = []

    def attempt(remaining: float) -> str:
        budgets.append(remaining)
        if len(budgets) < 4:
            raise TimeoutError
        return "done"

    result = retry_call(
        attempt,
        policy=policy(),
        sleep=seconds.advance,
        clock=seconds,
        is_idempotent=True,
        on_retry=lambda: retry_times.append(seconds()),
    )
    assert result == "done"
    assert budgets == [9, 8, 6, 4]
    assert retry_times == [1, 3, 5]


def test_seeded_jitter_stays_within_maximum_delay() -> None:
    seconds = ManualClock()
    retry_times: list[float] = []

    def fail(_: float) -> None:
        raise TimeoutError

    with pytest.raises(TimeoutError):
        retry_call(
            fail,
            policy=policy(jitter=0.5),
            sleep=seconds.advance,
            clock=seconds,
            rng=Random(1),
            is_idempotent=True,
            on_retry=lambda: retry_times.append(seconds()),
        )
    delays = [
        after - before for before, after in zip([0, *retry_times[:-1]], retry_times, strict=True)
    ]
    assert 0.5 <= delays[0] < 1
    assert all(1 <= delay <= 2 for delay in delays[1:])


def test_shared_deadline_prevents_sleeping_past_it() -> None:
    seconds = ManualClock()
    budgets: list[float] = []

    def slow_fail(remaining: float) -> None:
        budgets.append(remaining)
        seconds.advance(remaining - 0.25)
        raise TimeoutError("dependency timed out")

    with pytest.raises(TimeoutError, match="dependency timed out"):
        retry_call(
            slow_fail,
            policy=policy(),
            sleep=seconds.advance,
            clock=seconds,
            deadline=2,
            is_idempotent=True,
        )
    assert budgets == [2]
    assert seconds() == 1.75


def test_retry_discards_result_past_deadline() -> None:
    seconds = ManualClock()

    def late_success(remaining: float) -> str:
        seconds.advance(remaining + 0.25)
        return "too late"

    with pytest.raises(RetryBudgetExceeded):
        retry_call(
            late_success,
            policy=policy(),
            sleep=seconds.advance,
            clock=seconds,
            deadline=2,
            is_idempotent=True,
        )


@pytest.mark.parametrize("error", [ValueError(), CircuitOpen("test")])
def test_nonretryable_or_open_errors_stop_before_sleep(error: Exception) -> None:
    calls: list[float] = []
    sleeps: list[float] = []

    def fail(remaining: float) -> None:
        calls.append(remaining)
        raise error

    with pytest.raises(type(error)):
        retry_call(fail, policy=policy(), sleep=sleeps.append, clock=lambda: 0, is_idempotent=True)
    assert len(calls) == 1
    assert sleeps == []


def test_retries_require_idempotency_before_any_attempt() -> None:
    calls: list[float] = []
    with pytest.raises(ValueError, match="idempotent"):
        retry_call(calls.append, policy=policy(), is_idempotent=False)
    assert calls == []


def registry(clock: ManualClock, *, half_open: int = 1) -> CircuitRegistry:
    settings = CircuitSettings(failure_threshold=2, cool_down_s=10, half_open_max_calls=half_open)
    return CircuitRegistry(settings, clock=clock)


def fail() -> None:
    raise TimeoutError


def bug() -> None:
    raise ValueError


def open_circuit(circuits: CircuitRegistry, name: str = "milvus") -> None:
    for _ in range(2):
        with pytest.raises(TimeoutError):
            circuits.call(name, fail)


def test_circuit_opens_after_consecutive_failures_only() -> None:
    circuits = registry(ManualClock())
    with pytest.raises(TimeoutError):
        circuits.call("milvus", fail)
    with pytest.raises(ValueError):
        circuits.call("milvus", bug)
    with pytest.raises(TimeoutError):
        circuits.call("milvus", fail)
    assert circuits.state("milvus") == CircuitState.CLOSED
    with pytest.raises(TimeoutError):
        circuits.call("milvus", fail)
    assert circuits.state("milvus") == CircuitState.OPEN
    assert circuits.state("reranker") == CircuitState.CLOSED
    with pytest.raises(CircuitOpen):
        circuits.call("milvus", lambda: pytest.fail("open circuit called the dependency"))


def test_failed_probe_reopens_and_successful_probe_recovers() -> None:
    clock = ManualClock()
    circuits = registry(clock)
    open_circuit(circuits)
    clock.advance(10)
    assert circuits.state("milvus") == CircuitState.HALF_OPEN
    with pytest.raises(TimeoutError):
        circuits.call("milvus", fail)
    assert circuits.state("milvus") == CircuitState.OPEN
    clock.advance(10)
    assert circuits.call("milvus", lambda: "healthy") == "healthy"
    assert circuits.state("milvus") == CircuitState.CLOSED


def test_half_open_rejects_extra_concurrent_probes() -> None:
    clock = ManualClock()
    circuits = registry(clock)
    open_circuit(circuits)
    clock.advance(10)
    started, finish = Event(), Event()

    def probe() -> None:
        started.set()
        assert finish.wait(timeout=3)

    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(circuits.call, "milvus", probe)
        try:
            assert started.wait(timeout=3)
            with pytest.raises(CircuitOpen):
                circuits.call("milvus", lambda: pytest.fail("extra probe called dependency"))
        finally:
            finish.set()
        result.result(timeout=3)
    assert circuits.state("milvus") == CircuitState.CLOSED


def test_old_in_flight_success_does_not_close_newly_opened_circuit() -> None:
    clock = ManualClock()
    circuits = registry(clock)
    started, finish = Event(), Event()

    def previous_call() -> None:
        started.set()
        assert finish.wait(timeout=3)

    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(circuits.call, "orders_db", previous_call)
        try:
            assert started.wait(timeout=3)
            open_circuit(circuits, "orders_db")
        finally:
            finish.set()
        result.result(timeout=3)
    assert circuits.state("orders_db") == CircuitState.OPEN
