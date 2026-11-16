"""Build the local demo API and own graph lifetime and turn locks."""

import logging
import sqlite3
from asyncio import Lock
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import aclosing, asynccontextmanager
from pathlib import Path
from typing import Any

from anyio import CancelScope, fail_after, to_thread
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from sse_starlette import EventSourceResponse, JSONServerSentEvent
from starlette.types import Receive, Scope, Send

from support_agent.api.deps import ApiDeps
from support_agent.api.events import SseEvent
from support_agent.api.runner import Graph, TurnInput, failure_events, run_turn
from support_agent.api.schemas import (
    ChatRequest,
    ConversationRequest,
    HealthResponse,
    ResumeRequest,
)
from support_agent.graph.build import build_graph
from support_agent.graph.handoff import HandoffReason, load_templates
from support_agent.llm import resolve_model
from support_agent.orders.models import CustomerSummary

STATIC = Path(__file__).with_name("static")
logger = logging.getLogger(__name__)
_DB_ERRORS = (FileNotFoundError, sqlite3.Error)


def _encode(event: SseEvent) -> JSONServerSentEvent:
    return JSONServerSentEvent(event=event.name, data=event.model_dump(mode="json")["data"])


class TurnResponse(EventSourceResponse):
    def __init__(
        self, body: AsyncGenerator[JSONServerSentEvent, None], release: Callable[[], None]
    ) -> None:
        super().__init__(body)
        self.event_body = body
        self.release = release

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            try:
                with CancelScope(shield=True):
                    await self.event_body.aclose()
            finally:
                self.release()


def create_app(deps: ApiDeps) -> FastAPI:
    cfg = deps.settings.api
    system_error = load_templates("handoff_messages.yaml")[HandoffReason.SYSTEM_ERROR]
    locks: dict[str, Lock] = {}
    graph: Graph

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal graph
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
            yield
        finally:
            await to_thread.run_sync(deps.graph_deps.close)

    app = FastAPI(lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/customers")
    def customers() -> list[CustomerSummary]:
        try:
            return deps.order_service.list_customers(cfg.demo_customer_limit)
        except _DB_ERRORS as error:
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

    async def start_turn(request: ConversationRequest, turn_input: TurnInput) -> TurnResponse:
        try:
            exists = await to_thread.run_sync(
                deps.order_service.customer_exists, request.customer_id
            )
        except _DB_ERRORS as error:
            raise HTTPException(503, "Order database unavailable") from error
        if not exists:
            raise HTTPException(404, "Unknown customer")

        thread_id = f"{request.customer_id}:{request.conversation_id}"
        lock = locks.setdefault(thread_id, Lock())
        if lock.locked():
            raise HTTPException(409, "Conversation already running")
        await lock.acquire()

        def release() -> None:
            locks.pop(thread_id)
            lock.release()

        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

        async def body(error: Exception | None = None) -> AsyncGenerator[JSONServerSentEvent, None]:
            if error is not None:
                for event in failure_events(error, request.conversation_id, system_error):
                    yield _encode(event)
                return
            turn = run_turn(
                graph,
                turn_input,
                config,
                chunk_words=cfg.token_chunk_words,
                conversation_id=request.conversation_id,
                system_error_message=system_error,
            )
            async with aclosing(turn):
                async for event in turn:
                    yield _encode(event)

        try:
            if isinstance(turn_input, Command):
                try:
                    state = await to_thread.run_sync(graph.get_state, config)
                except Exception as error:
                    return TurnResponse(body(error), release)
                if not state.interrupts:
                    raise HTTPException(409, "Conversation has no pending order selection")
            return TurnResponse(body(), release)
        except BaseException:
            release()
            raise

    @app.post("/api/chat")
    async def chat(request: ChatRequest) -> TurnResponse:
        if len(request.message) > cfg.max_message_chars:
            raise HTTPException(422, "Message exceeds the configured length limit")
        payload: dict[str, Any] = {
            "messages": [HumanMessage(content=request.message)],
            "customer_id": request.customer_id,
        }
        return await start_turn(request, payload)

    @app.post("/api/resume")
    async def resume(request: ResumeRequest) -> TurnResponse:
        if len(request.value) > cfg.max_resume_chars:
            raise HTTPException(422, "Selection exceeds the configured length limit")
        return await start_turn(request, Command(resume=request.value.strip()))

    return app
