"""Measure the whole HTTP response, including streaming and cancellation."""

import logging
from time import perf_counter
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from support_agent.observability.metrics import ENDPOINTS, AtlasMetrics

logger = logging.getLogger(__name__)


def _outcome(status: int) -> str:
    if status == 409:
        return "conflict"
    if status == 503:
        return "unavailable"
    if status >= 500:
        return "error"
    if status >= 400:
        return "invalid"
    return "success"


class RequestMetricsMiddleware:
    def __init__(self, app: ASGIApp, metrics: AtlasMetrics) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        trace_id = uuid4().hex
        scope.setdefault("state", {})["trace_id"] = trace_id
        path = scope["path"]
        started = perf_counter()
        outcome = "error"

        async def instrumented_send(message: Message) -> None:
            nonlocal outcome
            if message["type"] == "http.response.start":
                outcome = _outcome(message["status"])
                message["headers"] = [
                    *message.get("headers", []),
                    (b"x-trace-id", trace_id.encode()),
                ]
            await send(message)

        try:
            await self.app(scope, receive, instrumented_send)
        except BaseException:
            outcome = "error"
            raise
        finally:
            outcome = scope["state"].get("atlas_metric_outcome", outcome)
            self.metrics.request(path, outcome, perf_counter() - started, trace_id)
            logger.info(
                "HTTP request trace_id=%s endpoint=%s outcome=%s",
                trace_id,
                ENDPOINTS.get(path, "other"),
                outcome,
            )
