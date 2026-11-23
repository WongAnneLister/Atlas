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

from support_agent.api.body_limit import BodyLimitMiddleware
from support_agent.api.deps import ApiDeps
from support_agent.api.events import SseEvent
from support_agent.api.http_metrics import RequestMetricsMiddleware
from support_agent.api.locks import ConversationLocks, LockUnavailable
from support_agent.api.readiness import ReadinessChecks, build_readiness, build_redis, readiness
from support_agent.api.runner import Graph, TurnInput, failure_events, run_turn
from support_agent.api.schemas import (
    ChatRequest,
    ConversationRequest,
    DeleteMemoriesResponse,
    HealthResponse,
    LiveResponse,
    ReadyResponse,
    ResumeRequest,
    SessionRequest,
    SessionResponse,
)
from support_agent.api.security import (
    SESSION_REQUIRED,
    RateLimits,
    RateLimitUnavailable,
    SessionAuthMiddleware,
    SessionTokens,
)
from support_agent.graph.build import build_graph
from support_agent.graph.handoff import HandoffReason, load_templates
from support_agent.infra.redis import RedisStore
from support_agent.llm import resolve_model
from support_agent.memory.long_term.models import PublicMemoryItem
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
    tokens = SessionTokens.from_environment(cfg.session)
    metrics = AtlasMetrics(deps.settings, deps.metrics_registry)
    deps.graph_deps.observer = metrics
    system_error = load_templates("handoff_messages.yaml")[HandoffReason.SYSTEM_ERROR]
    locks: ConversationLocks
    orders: GuardedOrders
    graph: Graph
    checks: ReadinessChecks
    rate_limits: RateLimits

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal graph, checks, locks, orders, rate_limits
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
                if store is not None and deps.graph_deps.cache_store is None:
                    deps.graph_deps.cache_store = store
                rate_limits = RateLimits(
                    cfg.rate_limit, store, shared=deps.settings.redis.backend == "redis"
                )
                locks = ConversationLocks(store, deps.settings.reliability.locks.conversation_ttl_s)
                orders = GuardedOrders(
                    lambda: deps.order_service, deps.graph_deps.dependency_guards
                )
                checks = deps.readiness or build_readiness(
                    deps.settings, deps.order_service, deps.milvus_check, resources, store
                )
                yield
        finally:
            if tracing.tracing_configured(deps.settings.tracing):
                await to_thread.run_sync(tracing.flush)
            await to_thread.run_sync(deps.graph_deps.close)

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(SessionAuthMiddleware, tokens=tokens)
    app.add_middleware(BodyLimitMiddleware, max_bytes=cfg.max_body_bytes)
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

    def is_demo_customer(customer_id: str) -> bool:
        return any(customer.customer_id == customer_id for customer in customers())

    async def limit(http: Request, customer_id: str | None = None) -> None:
        ip = http.client.host if http.client else "unknown"
        try:
            retry_after = await to_thread.run_sync(rate_limits.retry_after, ip, customer_id)
        except RateLimitUnavailable as error:
            raise HTTPException(503, "Rate limit unavailable") from error
        if retry_after is not None:
            raise HTTPException(429, "Too many requests", headers={"Retry-After": str(retry_after)})

    @app.post("/api/session")
    async def session(
        request: SessionRequest, http: Request, response: Response
    ) -> SessionResponse:
        await limit(http)
        if not await to_thread.run_sync(is_demo_customer, request.customer_id):
            # 403, not 404: the harness reads 404 as "this build has no session route".
            raise HTTPException(403, "Not a demo customer")
        response.headers["Cache-Control"] = "no-store"
        return SessionResponse(token=tokens.issue(request.customer_id))

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
        request: ConversationRequest,
        turn_input: TurnInput,
        text: str | None,
        http: Request,
        customer_id: str,
    ) -> TurnResponse:
        await limit(http, customer_id)
        trace_id: str = http.state.trace_id
        thread_id = f"{customer_id}:{request.conversation_id}"
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
                customer_id=customer_id,
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
            if not await to_thread.run_sync(is_demo_customer, customer_id):
                raise HTTPException(401, SESSION_REQUIRED, headers={"WWW-Authenticate": "Bearer"})
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
        customer_id: str = http.state.atlas_customer_id
        payload: dict[str, Any] = {
            "messages": [HumanMessage(content=request.message)],
            "customer_id": customer_id,
        }
        return await start_turn(request, payload, request.message, http, customer_id)

    @app.post("/api/resume")
    async def resume(request: ResumeRequest, http: Request) -> TurnResponse:
        if len(request.value) > cfg.max_resume_chars:
            raise HTTPException(422, "Selection exceeds the configured length limit")
        customer_id: str = http.state.atlas_customer_id
        return await start_turn(
            request, Command(resume=request.value.strip()), None, http, customer_id
        )

    @app.get("/api/me/memories")
    async def list_my_memories(http: Request) -> list[PublicMemoryItem]:
        customer_id: str = http.state.atlas_customer_id
        await limit(http, customer_id)
        store = deps.graph_deps.long_term_memory()
        if store is None:
            return []
        try:
            items = await to_thread.run_sync(store.list_active, customer_id)
        except _DB_ERRORS as error:
            raise HTTPException(503, "Memory store unavailable") from error
        return [
            PublicMemoryItem(
                id=m.id,
                kind=m.kind,
                content=m.content,
                created_at=m.created_at,
                expires_at=m.expires_at,
            )
            for m in items
        ]

    @app.delete("/api/me/memories/{memory_id}")
    async def delete_my_memory(memory_id: str, http: Request) -> DeleteMemoriesResponse:
        customer_id: str = http.state.atlas_customer_id
        await limit(http, customer_id)
        store = deps.graph_deps.long_term_memory()
        if store is None:
            raise HTTPException(404, "Memory not found")
        try:
            deleted = await to_thread.run_sync(store.soft_delete, customer_id, memory_id)
        except _DB_ERRORS as error:
            raise HTTPException(503, "Memory store unavailable") from error
        if not deleted:
            raise HTTPException(404, "Memory not found")
        return DeleteMemoriesResponse(deleted=1)

    @app.delete("/api/me/memories")
    async def delete_all_my_memories(http: Request) -> DeleteMemoriesResponse:
        customer_id: str = http.state.atlas_customer_id
        await limit(http, customer_id)
        store = deps.graph_deps.long_term_memory()
        if store is None:
            return DeleteMemoriesResponse(deleted=0)
        try:
            count = await to_thread.run_sync(store.soft_delete_all, customer_id)
        except _DB_ERRORS as error:
            raise HTTPException(503, "Memory store unavailable") from error
        return DeleteMemoriesResponse(deleted=count)

    return app
