"""Build the local demo API and own graph lifetime and turn locks."""

import hmac
import logging
import os
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

from support_agent.api.backpressure import CustomerAllowlistCache, InFlightLimiter
from support_agent.api.body_limit import BodyLimitMiddleware
from support_agent.api.budget import DailySpendCap
from support_agent.api.deps import ApiDeps
from support_agent.api.events import SseEvent
from support_agent.api.http_metrics import RequestMetricsMiddleware
from support_agent.api.locks import ConversationLocks, LockUnavailable
from support_agent.api.readiness import ReadinessChecks, build_readiness, build_redis, readiness
from support_agent.api.runner import Graph, TurnInput, failure_events, run_turn
from support_agent.api.schemas import (
    AgentClaimRequest,
    AgentReplyRequest,
    AgentResolveRequest,
    ChatRequest,
    ConversationRequest,
    DeleteMemoriesResponse,
    FeedbackRequest,
    FeedbackResponse,
    HealthResponse,
    LiveResponse,
    ReadyResponse,
    ResumeRequest,
    ReviewLabelRequest,
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
from support_agent.handoff.broker import HandoffEventBroker
from support_agent.handoff.models import HandoffItem, HandoffStatus
from support_agent.handoff.store import HandoffNotFoundError, HandoffQueueStore, HandoffStateError
from support_agent.infra.redis import RedisStore
from support_agent.llm import resolve_model
from support_agent.memory.long_term.models import PublicMemoryItem
from support_agent.observability import tracing
from support_agent.observability.metrics import AtlasMetrics
from support_agent.observability.online_store import ReviewStatus, SampledReviewRecord
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
    handoff_broker = HandoffEventBroker()
    in_flight = InFlightLimiter(cfg.concurrency.max_in_flight, cfg.concurrency.retry_after_s)
    spend_cap_usd = float(
        os.getenv("DEMO_DAILY_SPEND_CAP_USD", str(cfg.demo_budget.daily_spend_cap_usd))
    )
    spend_cap = DailySpendCap(spend_cap_usd)
    system_error = load_templates("handoff_messages.yaml")[HandoffReason.SYSTEM_ERROR]
    locks: ConversationLocks
    orders: GuardedOrders
    customer_cache: CustomerAllowlistCache
    graph: Graph
    checks: ReadinessChecks
    rate_limits: RateLimits

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal graph, checks, locks, orders, customer_cache, rate_limits
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
                customer_cache = CustomerAllowlistCache(
                    orders.list_customers,
                    ttl_s=cfg.concurrency.customer_cache_ttl_s,
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
    app.state.spend_cap = spend_cap
    app.add_middleware(SessionAuthMiddleware, tokens=tokens)
    app.add_middleware(BodyLimitMiddleware, max_bytes=cfg.max_body_bytes)
    app.add_middleware(RequestMetricsMiddleware, metrics=metrics)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/console")
    async def console_page() -> FileResponse:
        return FileResponse(STATIC / "console.html")

    @app.get("/api/customers")
    def customers() -> list[CustomerSummary]:
        try:
            return customer_cache.list_customers(cfg.demo_customer_limit)
        except Exception as error:
            if not isinstance(error, _DB_ERRORS) and not is_dependency_failure(error):
                raise
            raise HTTPException(503, "Order database unavailable") from error

    def is_demo_customer(customer_id: str) -> bool:
        try:
            return customer_cache.contains(customer_id, cfg.demo_customer_limit)
        except Exception as error:
            if not isinstance(error, _DB_ERRORS) and not is_dependency_failure(error):
                raise
            raise HTTPException(503, "Order database unavailable") from error

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
        if spend_cap.exceeded():

            async def budget_stream() -> AsyncGenerator[JSONServerSentEvent, None]:
                yield _encode(
                    SseEvent(
                        name="handoff",
                        data={
                            "reason": "demo_budget_reached",
                            "message": cfg.demo_budget.budget_reached_message,
                        },
                    )
                )
                yield _encode(
                    SseEvent(
                        name="done",
                        data={
                            "conversation_id": request.conversation_id,
                            "trace": ["demo_budget_cap"],
                        },
                    )
                )

            async def _noop_release() -> None:
                return None

            async def _noop_renew() -> bool:
                return True

            return TurnResponse(
                budget_stream(),
                _noop_release,
                _noop_renew,
                deps.settings.reliability.locks.renew_interval_s,
            )
        if not in_flight.try_acquire():
            raise HTTPException(
                503,
                "Server busy; please retry shortly.",
                headers={"Retry-After": str(in_flight.retry_after_s)},
            )
        trace_id: str = http.state.trace_id
        thread_id = f"{customer_id}:{request.conversation_id}"
        try:
            with CancelScope(shield=True):
                token = await to_thread.run_sync(locks.acquire, thread_id)
        except LockUnavailable as error:
            in_flight.release()
            raise HTTPException(503, "Conversation lock unavailable") from error
        except BaseException:
            in_flight.release()
            raise
        if token is None:
            in_flight.release()
            raise HTTPException(409, "Still answering your previous message. Please wait.")
        owner_token = token

        async def release() -> None:
            with CancelScope(shield=True):
                try:
                    await to_thread.run_sync(locks.release, thread_id, owner_token)
                finally:
                    in_flight.release()

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
                    if (
                        event.name == "done"
                        and isinstance(event.data, dict)
                        and isinstance(cost_usd := event.data.get("cost_usd"), int | float)
                    ):
                        spend_cap.record(float(cost_usd))
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

    def require_agent(http: Request) -> None:
        expected = os.getenv("AGENT_TOKEN") or deps.settings.handoff.demo_agent_token
        auth = http.headers.get("authorization", "")
        parts = auth.split()
        if len(parts) != 2 or parts[0].casefold() != "bearer":
            raise HTTPException(401, "Agent token required", headers={"WWW-Authenticate": "Bearer"})
        if not hmac.compare_digest(parts[1], expected):
            raise HTTPException(401, "Invalid agent token", headers={"WWW-Authenticate": "Bearer"})

    def require_handoff_queue() -> HandoffQueueStore:
        queue = deps.graph_deps.handoff_queue()
        if queue is None:
            raise HTTPException(503, "Handoff queue is disabled")
        return queue

    @app.get("/api/conversations/{conversation_id}/events")
    async def conversation_events(conversation_id: str, http: Request) -> EventSourceResponse:
        customer_id: str = http.state.atlas_customer_id
        thread_id = f"{customer_id}:{conversation_id}"

        async def stream() -> AsyncGenerator[JSONServerSentEvent, None]:
            async for event_name, data in handoff_broker.subscribe(thread_id):
                yield JSONServerSentEvent(event=event_name, data=data)
                if event_name == "handoff_resolved":
                    return

        return EventSourceResponse(stream())

    @app.get("/api/agent/handoffs")
    async def agent_list_handoffs(
        http: Request, status: HandoffStatus | None = None
    ) -> list[HandoffItem]:
        require_agent(http)
        queue = require_handoff_queue()
        return await to_thread.run_sync(lambda: queue.list_items(status=status))

    @app.get("/api/agent/handoffs/{handoff_id}")
    async def agent_get_handoff(handoff_id: str, http: Request) -> HandoffItem:
        require_agent(http)
        queue = require_handoff_queue()
        item = await to_thread.run_sync(queue.get, handoff_id)
        if item is None:
            raise HTTPException(404, "Handoff not found")
        return item

    @app.post("/api/agent/handoffs/{handoff_id}/claim")
    async def agent_claim_handoff(
        handoff_id: str, request: AgentClaimRequest, http: Request
    ) -> HandoffItem:
        require_agent(http)
        queue = require_handoff_queue()
        try:
            return await to_thread.run_sync(queue.claim, handoff_id, request.agent_id)
        except HandoffNotFoundError as error:
            raise HTTPException(404, str(error)) from error
        except HandoffStateError as error:
            raise HTTPException(409, str(error)) from error

    @app.post("/api/agent/handoffs/{handoff_id}/reply")
    async def agent_reply_handoff(
        handoff_id: str, request: AgentReplyRequest, http: Request
    ) -> HandoffItem:
        require_agent(http)
        queue = require_handoff_queue()
        try:
            item = await to_thread.run_sync(
                lambda: queue.add_message(
                    handoff_id,
                    sender="agent",
                    author=request.agent_id,
                    text=request.message,
                )
            )
        except HandoffNotFoundError as error:
            raise HTTPException(404, str(error)) from error
        except HandoffStateError as error:
            raise HTTPException(409, str(error)) from error
        thread_id = f"{item.customer_id}:{item.conversation_id}"
        handoff_broker.publish(
            thread_id,
            "agent_reply",
            {
                "handoff_id": item.id,
                "agent_id": request.agent_id,
                "text": request.message.strip(),
            },
        )
        return item

    @app.post("/api/agent/handoffs/{handoff_id}/resolve")
    async def agent_resolve_handoff(
        handoff_id: str, request: AgentResolveRequest, http: Request
    ) -> HandoffItem:
        require_agent(http)
        queue = require_handoff_queue()
        try:
            item = await to_thread.run_sync(
                lambda: queue.resolve(
                    handoff_id,
                    agent_id=request.agent_id,
                    label=request.label,
                    note=request.note,
                    hand_back_to_ai=request.hand_back_to_ai,
                )
            )
        except HandoffNotFoundError as error:
            raise HTTPException(404, str(error)) from error
        except HandoffStateError as error:
            raise HTTPException(409, str(error)) from error

        thread_id = f"{item.customer_id}:{item.conversation_id}"
        if request.hand_back_to_ai:
            config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
            try:
                await to_thread.run_sync(
                    lambda: graph.update_state(
                        config, {"human_mode": False, "active_handoff_id": None}
                    )
                )
            except Exception as error:
                logger.warning("Failed to clear human_mode checkpoint: %s", type(error).__name__)
        handoff_broker.publish(
            thread_id,
            "handoff_resolved",
            {
                "handoff_id": item.id,
                "label": request.label,
                "hand_back_to_ai": request.hand_back_to_ai,
            },
        )
        return item

    @app.post("/api/feedback")
    async def submit_feedback(request: FeedbackRequest, http: Request) -> FeedbackResponse:
        customer_id: str = http.state.atlas_customer_id
        await limit(http, customer_id)
        store = deps.graph_deps.online_eval()
        if store is None:
            raise HTTPException(503, "Online feedback storage is disabled")
        record, created = await to_thread.run_sync(
            lambda: store.record_feedback(
                message_id=request.message_id,
                conversation_id=request.conversation_id,
                customer_id=customer_id,
                rating=request.rating,
                reason=request.reason,
                trace_id=request.trace_id,
            )
        )
        if created:
            metrics.record_feedback(request.rating)
            try:
                await to_thread.run_sync(
                    lambda: tracing.record_feedback_score(
                        deps.settings.tracing,
                        trace_id=request.trace_id,
                        rating=request.rating,
                        reason=request.reason,
                    )
                )
            except Exception as error:
                logger.warning("Async feedback score failed: %s", type(error).__name__)
        return FeedbackResponse(
            id=record.id,
            message_id=record.message_id,
            rating=record.rating,
            created=created,
        )

    @app.get("/api/agent/reviews")
    async def agent_list_reviews(
        http: Request, status: ReviewStatus | None = None
    ) -> list[SampledReviewRecord]:
        require_agent(http)
        store = deps.graph_deps.online_eval()
        if store is None:
            return []
        return await to_thread.run_sync(lambda: store.list_reviews(status=status))

    @app.post("/api/agent/reviews/{review_id}/label")
    async def agent_label_review(
        review_id: str, request: ReviewLabelRequest, http: Request
    ) -> SampledReviewRecord:
        require_agent(http)
        store = deps.graph_deps.online_eval()
        if store is None:
            raise HTTPException(503, "Online eval store is disabled")
        updated = await to_thread.run_sync(
            lambda: store.label_review(
                review_id,
                reviewer_id=request.reviewer_id,
                rubric_label=request.rubric_label,
                note=request.note,
            )
        )
        if updated is None:
            raise HTTPException(404, "Review item not found")
        return updated

    return app
