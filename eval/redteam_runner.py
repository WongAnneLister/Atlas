"""Drive the Atlas API with synthetic data over an in-process ASGI transport."""

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal

import httpx
from anyio import to_thread
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langsmith import tracing_context
from prometheus_client import CollectorRegistry
from pydantic import BaseModel, Field, JsonValue
from sqlalchemy import select

from eval.judge import JudgeDecision
from eval.redteam_canaries import ATTACKER_CUSTOMER
from eval.redteam_checks import Observation, ObservedRefund, ObservedTurn
from eval.redteam_fixtures import (
    FIXTURE_CUSTOMER_IDS,
    FIXTURE_ORDER_IDS,
    FixtureHooks,
    RedTeamFixtures,
    open_fixtures,
)
from eval.redteam_models import Category, RedTeamItem, Turn
from eval.redteam_scoring import score
from support_agent.api.app import create_app
from support_agent.api.deps import ApiDeps
from support_agent.api.events import SseEvent
from support_agent.api.readiness import ReadinessChecks
from support_agent.config import Settings
from support_agent.graph.deps import GraphDeps
from support_agent.graph.handoff import HandoffReason
from support_agent.graph.postgres import checkpoint_serializer
from support_agent.graph.state import CitationRecord, ConversationState
from support_agent.graph.turn_identity import action_key, turn_message_id
from support_agent.infra.redis import NullRedis
from support_agent.orders.tables import refund_requests
from support_agent.retrieval.types import RetrievedChunk, Retriever

_SSE_NAMES = frozenset({"token", "citations", "handoff", "meta", "interrupt", "done", "error"})
_STRUCTURED_ERRORS = frozenset(
    {"ValidationError", "OutputParserException", "JSONDecodeError", "ValueError"}
)


class TurnOutcome(BaseModel):
    kind: Literal["chat", "resume"]
    http_status: int
    events: list[SseEvent] = Field(default_factory=list)
    route: list[str] = Field(default_factory=list)
    answer: str = ""
    handoff_reason: str | None = None
    handoff_text: str | None = None
    refund_key: str | None = None
    refund_request: dict[str, JsonValue] | None = None
    tool_results: list[JsonValue] = Field(default_factory=list)
    citations: list[CitationRecord] = Field(default_factory=list)
    retrieval: list[RetrievedChunk] = Field(default_factory=list)
    error_type: str | None = None

    def observation(self) -> ObservedTurn:
        return ObservedTurn(
            route=self.route,
            answer=self.answer,
            citation_numbers=[citation.n for citation in self.citations],
            handoff_text=self.handoff_text,
            refund_key=self.refund_key,
            tool_results=self.tool_results,
        )


class ItemOutcome(BaseModel):
    item_id: str
    category: Category
    status: Literal["success", "failure", "error"]
    evidence: str | None = None
    error_type: str | None = None
    judged_fabrication: bool | None = None
    judge_used: bool = False
    judge_claims: list[str] = Field(default_factory=list)
    turns: list[TurnOutcome] = Field(default_factory=list)


class JudgeInput(BaseModel):
    item_id: str
    turn_index: int
    question: str
    answer: str
    sources: list[RetrievedChunk]


Judge = Callable[[JudgeInput], JudgeDecision]


class _FixtureGraph(GraphDeps):
    def __init__(
        self,
        fixtures: RedTeamFixtures,
        hooks: FixtureHooks,
        fast_model: BaseChatModel | None,
        main_model: BaseChatModel | None,
        retriever: Retriever | None,
    ) -> None:
        super().__init__(
            fixtures.settings,
            fast_model=fast_model,
            main_model=main_model,
            retriever=retriever,
            order_service=fixtures.orders,
            model_messages=hooks.model_messages,
        )
        # With no injected fake, GraphDeps uses GuardedMilvusSearch (read methods only).
        self._overlay = hooks.overlay(super().knowledge_retriever)
        self._checkpointer = InMemorySaver(serde=checkpoint_serializer())

    def knowledge_retriever(self) -> Retriever:
        return self._overlay


def _events(response: httpx.Response) -> list[SseEvent]:
    if not response.headers.get("content-type", "").startswith("text/event-stream"):
        raise ValueError("Expected an event stream")
    events = []
    text = response.text.replace("\r\n", "\n")
    for block in text.split("\n\n"):
        fields: dict[str, list[str]] = {}
        for line in block.splitlines():
            if not line or line.startswith(":"):
                continue
            key, colon, value = line.partition(":")
            if not colon or key not in {"event", "data", "id", "retry"}:
                raise ValueError("Malformed event field")
            fields.setdefault(key, []).append(value.removeprefix(" "))
        if not fields:
            continue
        names = fields.get("event", [])
        if len(names) != 1 or names[0] not in _SSE_NAMES or not fields.get("data"):
            raise ValueError("Malformed event")
        events.append(SseEvent(name=names[0], data=json.loads("\n".join(fields["data"]))))
    return events


def _dependency_failure(state: ConversationState) -> str | None:
    if state.retrieval_error_type:
        return state.retrieval_error_type
    if state.handoff and state.handoff.reason in {
        HandoffReason.DEPENDENCY_UNAVAILABLE,
        HandoffReason.SYSTEM_ERROR,
    }:
        return state.handoff.reason.value
    return next(
        (
            event.error_type
            for event in state.reliability_events
            if event.role is not None
            and event.error_type is not None
            and event.error_type not in _STRUCTURED_ERRORS
        ),
        None,
    )


class _TurnData(BaseModel):
    trace: list[str]


class _MessageData(BaseModel):
    message: str


class _TextData(BaseModel):
    text: str


class _SessionResponse(BaseModel):
    token: str = Field(min_length=1)


async def _session_token(client: httpx.AsyncClient) -> str | None:
    response = await client.post("/api/session", json={"customer_id": ATTACKER_CUSTOMER})
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise ValueError("The synthetic customer could not open an API session")
    try:
        return _SessionResponse.model_validate_json(response.content).token
    except ValueError:
        raise ValueError("Invalid fixture session response") from None


async def _submit_turn(
    client: httpx.AsyncClient, item: RedTeamItem, turn: Turn, token: str | None
) -> tuple[httpx.Response, str]:
    body_customer_id = turn.body_customer_id or ATTACKER_CUSTOMER
    if body_customer_id not in FIXTURE_CUSTOMER_IDS:
        raise ValueError("Evaluation must use synthetic fixture identities")
    field = "message" if turn.kind == "chat" else "value"
    body = {"customer_id": body_customer_id, "conversation_id": item.id, field: turn.text}
    headers = {"Authorization": f"Bearer {token}"} if token is not None else None
    response = await client.post(f"/api/{turn.kind}", json=body, headers=headers)
    return response, ATTACKER_CUSTOMER if token is not None else body_customer_id


def _observation(outcome: TurnOutcome, item: RedTeamItem) -> ObservedTurn:
    observed = outcome.observation()
    if item.category == "identity_spoofing":
        # A picker is customer-visible output too. Keep the v1 text inputs unchanged.
        pickers = [
            json.dumps(event.data, default=str)
            for event in outcome.events
            if event.name == "interrupt"
        ]
        observed.answer = "\n".join([observed.answer, *pickers])
    return observed


async def _run_turn(
    client: httpx.AsyncClient,
    saver: BaseCheckpointSaver[Any],
    hooks: FixtureHooks,
    item: RedTeamItem,
    turn: Turn,
    token: str | None,
) -> TurnOutcome:
    with hooks.capture(item.fixtures.overlay_chunk_ids) as tool_results:
        response, customer_id = await _submit_turn(client, item, turn, token)
    config: RunnableConfig = {"configurable": {"thread_id": f"{customer_id}:{item.id}"}}
    outcome = TurnOutcome(
        kind=turn.kind, http_status=response.status_code, tool_results=tool_results
    )
    if response.status_code != 200:
        if (
            turn.kind == "resume"
            and response.status_code == 409
            and response.json() == {"detail": "Conversation has no pending order selection"}
        ):
            return outcome
        outcome.error_type = f"HTTP_{response.status_code}"
        return outcome

    outcome.events = _events(response)
    names = [event.name for event in outcome.events]
    if "error" in names:
        outcome.error_type = "ApiStreamError"
        return outcome
    if names[-1:] != ["done"] or names.count("done") != 1:
        raise ValueError("Missing terminal event")
    outcome.route = _TurnData.model_validate(outcome.events[-1].data).trace

    checkpoint = saver.get(config)
    if checkpoint is None:
        raise ValueError("Missing turn checkpoint")
    state = ConversationState.model_validate(checkpoint["channel_values"])
    if state.customer_id != customer_id or not outcome.route:
        raise ValueError("Invalid turn checkpoint")
    outcome.answer = "".join(
        _TextData.model_validate(event.data).text
        for event in outcome.events
        if event.name == "token"
    )
    for event in outcome.events:
        if event.name == "handoff":
            outcome.handoff_text = _MessageData.model_validate(event.data).message
            outcome.handoff_reason = state.handoff.reason.value if state.handoff else None
    outcome.answer = outcome.handoff_text or outcome.answer
    if state.answer != outcome.answer:
        raise ValueError("Public response does not match turn checkpoint")
    outcome.refund_key = action_key(config, turn_message_id(state.messages), "refund_request")
    outcome.refund_request = state.refund_request
    outcome.citations = state.citations
    outcome.retrieval = state.retrieval
    outcome.error_type = _dependency_failure(state)
    return outcome


def _refunds(fixtures: RedTeamFixtures, turns: list[TurnOutcome]) -> list[ObservedRefund]:
    keys = [turn.refund_key for turn in turns if turn.refund_key is not None]
    if not keys:
        return []
    query = select(refund_requests.c.order_id, refund_requests.c.idempotency_key).where(
        refund_requests.c.idempotency_key.in_(keys)
    )
    with fixtures.orders.repository.connection() as connection:
        return [
            ObservedRefund(order_id=order_id, idempotency_key=key)
            for order_id, key in connection.execute(query)
        ]


async def _judge(
    item: RedTeamItem, outcomes: list[TurnOutcome], judge: Judge | None
) -> tuple[bool | None, bool, list[str]]:
    if item.success.kind != "fabricated_commitment" or judge is None:
        return None, False, []
    question = ""
    flagged = False
    used = False
    claims: list[str] = []
    for index, (turn, outcome) in enumerate(zip(item.turns, outcomes, strict=True), 1):
        if turn.kind == "chat":
            question = turn.text
        if not outcome.answer.strip() or outcome.handoff_text:
            continue
        citation_ids = {citation.chunk_id for citation in outcome.citations}
        judge_input = JudgeInput(
            item_id=item.id,
            turn_index=index,
            question=question,
            answer=outcome.answer,
            sources=[chunk for chunk in outcome.retrieval if chunk.chunk_id in citation_ids],
        )
        decision = await to_thread.run_sync(judge, judge_input)
        flagged = decision.flagged or flagged
        claims.extend(decision.claims if decision.flagged else [])
        used = True
    return flagged, used, claims


async def _run_item(
    item: RedTeamItem,
    fixtures: RedTeamFixtures,
    client: httpx.AsyncClient,
    saver: BaseCheckpointSaver[Any],
    hooks: FixtureHooks,
    judge: Judge | None,
    token: str | None,
) -> ItemOutcome:
    record = ItemOutcome(item_id=item.id, category=item.category, status="error")
    try:
        if (
            item.attacker_customer != ATTACKER_CUSTOMER
            or set(item.target.customer_ids) - FIXTURE_CUSTOMER_IDS
            or set(item.fixtures.order_ids + item.target.order_ids) - FIXTURE_ORDER_IDS
        ):
            raise ValueError("Evaluation targets must use synthetic fixture identities")
        for turn in item.turns:
            outcome = await _run_turn(client, saver, hooks, item, turn, token)
            record.turns.append(outcome)
            if outcome.error_type is not None:
                record.error_type = outcome.error_type
                return record
        (
            record.judged_fabrication,
            record.judge_used,
            record.judge_claims,
        ) = await _judge(item, record.turns, judge)
        checked = score(
            item,
            Observation(
                turns=[_observation(turn, item) for turn in record.turns],
                refunds=_refunds(fixtures, record.turns),
                canaries=fixtures.canaries,
                foreign_fields=fixtures.foreign_fields,
                judged_fabrication=record.judged_fabrication,
            ),
            [turn.handoff_reason for turn in record.turns],
        )
        record.status = "success" if checked.success else "failure"
        record.evidence = checked.evidence
    except Exception as error:
        record.error_type = type(error).__name__
    return record


async def run(
    items: Sequence[RedTeamItem],
    *,
    settings: Settings,
    run_dir: Path,
    fast_model: BaseChatModel | None = None,
    main_model: BaseChatModel | None = None,
    retriever: Retriever | None = None,
    judge: Judge | None = None,
) -> list[ItemOutcome]:
    if len({item.id for item in items}) != len(items):
        raise ValueError("Red-team item IDs must be unique within a run")
    with open_fixtures(settings, run_dir) as fixtures, tracing_context(enabled=False):
        # A fake role must never fall through to a network provider on an error.
        if fast_model is not None:
            fixtures.settings.llm.fallbacks.fast.clear()
        if main_model is not None:
            fixtures.settings.llm.fallbacks.main.clear()
        hooks = FixtureHooks(fixtures.canaries["system_prompt"])
        deps = _FixtureGraph(fixtures, hooks, fast_model, main_model, retriever)
        app = create_app(
            ApiDeps(
                settings=fixtures.settings,
                graph_deps=deps,
                order_service=fixtures.orders,
                milvus_check=lambda: False,
                readiness=ReadinessChecks(),
                lock_store=NullRedis(),
                metrics_registry=CollectorRegistry(),
            )
        )
        saver = deps.checkpointer()
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                base_url="http://atlas-redteam.test",
                transport=httpx.ASGITransport(app=app),
                trust_env=False,
            ) as client,
        ):
            token = await _session_token(client)
            return [
                await _run_item(item, fixtures, client, saver, hooks, judge, token)
                for item in items
            ]
