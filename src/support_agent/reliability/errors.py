"""Identify transient dependency failures without requiring optional provider SDKs."""

import httpx


class CircuitOpen(RuntimeError):
    """The dependency is cooling down or all recovery probes are occupied."""

    def __init__(self, dependency: str) -> None:
        self.dependency = dependency
        super().__init__(f"Circuit is open for {dependency}")


class RetryBudgetExceeded(TimeoutError):
    """There is no time left for the dependency operation."""


class InjectedTimeout(TimeoutError):
    """A chaos injector simulated a timeout."""


class InjectedRateLimit(RuntimeError):
    """A chaos injector simulated an HTTP rate-limit response."""

    status_code = 429


def is_retryable(error: BaseException) -> bool:
    if isinstance(
        error,
        (
            TimeoutError,
            ConnectionError,
            CircuitOpen,
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.ProxyError,
            httpx.RemoteProtocolError,
        ),
    ):
        return True
    # OpenAI-compatible and Anthropic clients expose HTTP status directly.
    # HTTPX's status exception exposes it on its response instead.
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(getattr(error, "response", None), "status_code", None)
    if isinstance(status, int):
        return status == 429 or 500 <= status < 600
    # These wrappers have no status and may be raised without a chained HTTPX error.
    return any(
        cls.__name__ == "APIConnectionError"
        and cls.__module__.split(".", 1)[0] in {"openai", "anthropic"}
        for cls in type(error).__mro__
    )
