"""Build the local demo API and own graph lifetime and turn locks."""

import logging
import sqlite3
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from contextlib import ExitStack, aclosing, asynccontextmanager
from pathlib import Path
from typing import Any

from anyio import CancelScope, create_task_group, fail_after, sleep, to_thread
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from sqlalchemy.exc import SQLAlchemyError
from sse_starlette import EventSourceResponse, JSONServerSentEvent
from starlette.types import Receive, Scope, Send

from support_agent.api.deps import ApiDeps
from support_agent.api.events import SseEvent
from support_agent.api.http_metrics import RequestMetricsMiddleware
from support_agent.api.locks import ConversationLocks, LockUnavailable
from support_agent.api.readiness import ReadinessChecks, build_readiness, build_redis, readiness
from support_agent.api.runner import Graph, TurnInput, failure_events, run_turn
from support_agent.api.schemas import (
    ChatRequest,
    ConversationRequest,
    HealthResponse,
    LiveResponse,
    ReadyResponse,
    ResumeRequest,
)
from support_agent.graph.build import build_graph
from support_agent.graph.handoff import HandoffReason, load_templates
from support_agent.infra.redis import RedisStore
from support_agent.llm import resolve_model
from support_agent.observability import tracing
from support_agent.observability.metrics import AtlasMetrics
from support_agent.orders.models import CustomerSummary
from support_agent.reliability.guards import is_dependency_failure
from support_agent.reliability.stores import GuardedOrders

STATIC = Path(__file__).with_name("static")
logger = logging.getLogger(__name__)
_DB_ERRORS = (FileNotFoundError, sqlite3.Error, SQLAlchemyError)


def _encode(event: SseEvent) -> JSONServerSentEvent:
    return JSONServerSentEvent(event=event.name, data=event.model_dump(mode="json")["data"])


class TurnResponse(EventSourceResponse):
    def __init__(
        self,
        body: AsyncGenerator[JSONServerSentEvent, None],
        release: Callable[[], Awaitable[None]],
        renew: Callable[[], Awaitable[bool]],
        renew_interval_s: float,
    ) -> None:
        super().__init__(body)
        self.event_body = body
        self.release = release
        self.renew = renew
        self.renew_interval_s = renew_interval_s

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            async with create_task_group() as tasks:

                async def keep_lease() -> None:
                    while True:
                        await sleep(self.renew_interval_s)
                        if not await self.renew():
                            scope["state"]["atlas_metric_outcome"] = "error"
                            logger.warning("Ending stream after conversation lease renewal failed")
                            tasks.cancel_scope.cancel()
                            return

                tasks.start_soon(keep_lease)
                try:
                    await super().__call__(scope, receive, send)
                finally:
                    tasks.cancel_scope.cancel()
        finally:
            with CancelScope(shield=True):
                try:
                    await self.event_body.aclose()
                finally:
                    await self.release()


def create_app(deps: ApiDeps) -> FastAPI:
    cfg = deps.settings.api
    metrics = AtlasMetrics(deps.settings, deps.metrics_registry)
    deps.graph_deps.observer = metrics
    system_error = load_templates("handoff_messages.yaml")[HandoffReason.SYSTEM_ERROR]
    locks: ConversationLocks
    orders: GuardedOrders
    graph: Graph
    checks: ReadinessChecks

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal graph, checks, locks, orders
        try:
            graph = await to_thread.run_sync(build_graph, deps.graph_deps)
            if deps.warmup:
                try:
                    await to_thread.run_sync(
                        lambda: deps.graph_deps.knowledge_retriever().retrieve(
                            "Return policy", deps.settings.retrieval.rerank_top_k
                        )
                    )
                except Exception as error:
                    logger.warning("Retriever warmup failed: %s", type(error).__name__)
            with ExitStack() as resources:
                store = deps.lock_store
                if store is None:
                    try:
                        store = build_redis(deps.settings)
                    except (TypeError, ValueError) as error:
                        logger.warning("Redis configuration failed: %s", type(error).__name__)
                    else:
                        if isinstance(store, RedisStore):
                            resources.callback(store.close)
                locks = ConversationLocks(store, deps.settings.reliability.locks.conversation_ttl_s)
                orders = GuardedOrders(
                    lambda: deps.order_service, deps.graph_deps.dependency_guards
                )
                checks = deps.readiness or build_readiness(
                    deps.settings, deps.order_service, deps.milvus_check, resources, store
                )
                yield
        finally:
            await to_thread.run_sync(tracing.flush)
            await to_thread.run_sync(deps.graph_deps.close)

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(RequestMetricsMiddleware, metrics=metrics)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/customers")
    def customers() -> list[CustomerSummary]:
        try:
            return orders.list_customers(cfg.demo_customer_limit)
        except Exception as error:
            if not isinstance(error, _DB_ERRORS) and not is_dependency_failure(error):
                raise
            raise HTTPException(503, "Order database unavailable") from error

    @app.get("/api/health")
    async def health() -> HealthResponse:
        try:
            with fail_after(cfg.health_timeout_s):
                milvus = await to_thread.run_sync(deps.milvus_check, abandon_on_cancel=True)
        except Exception:
            milvus = False
        try:
            await to_thread.run_sync(deps.order_service.list_customers, 1)
            order_db = True
        except _DB_ERRORS:
            order_db = False
        llm = deps.settings.llm
        models = all(resolve_model("fast", llm)) and all(resolve_model("main", llm))
        return HealthResponse(
            status="ok" if milvus and order_db and models else "degraded",
            milvus=milvus,
            order_db=order_db,
            models_configured=models,
        )

    @app.get("/api/health/live")
    async def live() -> LiveResponse:
        return LiveResponse()

    @app.get("/api/health/ready")
    async def ready(response: Response) -> ReadyResponse:
        result = await readiness(checks, deps.settings.readiness)
        if result.status == "down":
            response.status_code = 503
        return result

    @app.get("/metrics", include_in_schema=False)
    def prometheus(http: Request) -> Response:
        data, content_type = metrics.render(
            deps.graph_deps.circuits, http.headers.get("accept", "")
        )
        return Response(content=data, headers={"content-type": content_type})

    async def start_turn(
        request: ConversationRequest, turn_input: TurnInput, text: str | None, http: Request
    ) -> TurnResponse:
        trace_id: str = http.state.trace_id
        thread_id = f"{request.customer_id}:{request.conversation_id}"
        try:
            with CancelScope(shield=True):
                token = await to_thread.run_sync(locks.acquire, thread_id)
        except LockUnavailable as error:
            raise HTTPException(503, "Conversation lock unavailable") from error
        if token is None:
            raise HTTPException(409, "Still answering your previous message. Please wait.")
        owner_token = token

        async def release() -> None:
            with CancelScope(shield=True):
                await to_thread.run_sync(locks.release, thread_id, owner_token)

        async def renew() -> bool:
            return await to_thread.run_sync(locks.refresh, thread_id, owner_token)

        config: RunnableConfig = {
            "configurable": {"thread_id": thread_id},
            "metadata": {"trace_id": trace_id},
        }

        async def body(error: Exception | None = None) -> AsyncGenerator[JSONServerSentEvent, None]:
            if error is not None:
                http.state.atlas_metric_outcome = "error"
                for event in failure_events(
                    error, request.conversation_id, system_error, trace_id=trace_id, metrics=metrics
                ):
                    yield _encode(event)
                return
            trace = tracing.start_turn(
                deps.settings,
                name="chat_turn" if text is not None else "resume_turn",
                conversation_id=request.conversation_id,
                customer_id=request.customer_id,
                input_text=text,
                trace_id=trace_id,
            )
            turn = run_turn(
                graph,
                turn_input,
                config,
                chunk_words=cfg.token_chunk_words,
                conversation_id=request.conversation_id,
                system_error_message=system_error,
                trace=trace,
                costs=deps.settings.costs,
                metrics=metrics,
                trace_id=trace_id,
            )
            async with aclosing(turn):
                async for event in turn:
                    if event.name == "error":
                        http.state.atlas_metric_outcome = "error"
                    yield _encode(event)

        def response(error: Exception | None = None) -> TurnResponse:
            return TurnResponse(
                body(error), release, renew, deps.settings.reliability.locks.renew_interval_s
            )

        try:
            try:
                exists = await to_thread.run_sync(orders.customer_exists, request.customer_id)
            except Exception as error:
                if not isinstance(error, _DB_ERRORS) and not is_dependency_failure(error):
                    raise
                raise HTTPException(503, "Order database unavailable") from error
            if not exists:
                raise HTTPException(404, "Unknown customer")
            if isinstance(turn_input, Command):
                try:
                    with fail_after(deps.settings.reliability.timeouts_s.orders_db):
                        state = await to_thread.run_sync(
                            graph.get_state, config, abandon_on_cancel=True
                        )
                except Exception as error:
                    return response(error)
                if not state.interrupts:
                    raise HTTPException(409, "Conversation has no pending order selection")
            return response()
        except BaseException:
            await release()
            raise

    @app.post("/api/chat")
    async def chat(request: ChatRequest, http: Request) -> TurnResponse:
        if len(request.message) > cfg.max_message_chars:
            raise HTTPException(422, "Message exceeds the configured length limit")
        payload: dict[str, Any] = {
            "messages": [HumanMessage(content=request.message)],
            "customer_id": request.customer_id,
        }
        return await start_turn(request, payload, request.message, http)

    @app.post("/api/resume")
    async def resume(request: ResumeRequest, http: Request) -> TurnResponse:
        if len(request.value) > cfg.max_resume_chars:
            raise HTTPException(422, "Selection exceeds the configured length limit")
        return await start_turn(request, Command(resume=request.value.strip()), None, http)

    return app
