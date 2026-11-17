"""Offline coverage of public chat routes and graph event mapping."""

import asyncio
import json
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest

from support_agent.api.app import create_app
from support_agent.api.deps import ApiDeps
from support_agent.api.events import events_for_update
from support_agent.api.runner import Graph
from support_agent.graph.deps import GraphDeps
from support_agent.graph.intents import Intent
from support_agent.graph.nodes.knowledge import KnowledgePath
from test_graph_knowledge import BrokenRetriever, CoverageFake, FixedRetriever, evidence, part
from test_refund_flow import DecisionFake, fast, yes_decision
from test_refund_flow import FixedRetriever as RefundRetriever

REQUEST = {"conversation_id": "chat-1", "customer_id": "CUST-0001"}
QUESTION = {"message": "What is the return window?", **REQUEST}


def refundable_order(service: Any) -> Any:
    return next(
        order
        for order in service.list_recent_orders(REQUEST["customer_id"])
        if order.items[0].refunded_quantity < order.items[0].quantity
    )


@asynccontextmanager
async def client(
    seeded: Any,
    *,
    refund: bool = False,
    score: float = 0.99,
    milvus: Callable[[], bool] = lambda: True,
    retriever: Any = None,
    configure_models: bool = True,
) -> AsyncIterator[httpx.AsyncClient]:
    settings, service = seeded
    settings.graph.checkpoint_backend = "memory"
    settings.gate.threshold = 0.5
    settings.api.demo_customer_limit = 2
    settings.api.token_chunk_words = 2
    model = "fake" if configure_models else None
    settings.llm.provider = settings.llm.fast_model = settings.llm.main_model = model
    if refund:
        order = refundable_order(service)
        status = order.status.value.replace("_", " ")
        deps = GraphDeps(
            settings,
            fast_model=fast(),
            main_model=DecisionFake(responses=["unused"], decisions=[yes_decision(order)]),
            retriever=RefundRetriever(text=f"{status} refund policy for final sale."),
            order_service=service,
        )
    else:
        classifier = fast(Intent.POLICY_QUESTION)
        classifier.predictions.append({"intent": Intent.CHITCHAT_OTHER, "confidence": 0.99})
        deps = GraphDeps(
            settings,
            fast_model=classifier,
            main_model=CoverageFake(responses=["unused"], payload={"parts": [part()]}),
            retriever=retriever or FixedRetriever(evidence(score)),
            order_service=service,
        )
    app = create_app(ApiDeps(settings, deps, service, milvus))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as api,
    ):
        yield api


def events(response: httpx.Response) -> list[tuple[str, Any]]:
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    blocks = response.text.replace("\r\n", "\n").strip().split("\n\n")
    return [
        (lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: ")))
        for block in blocks
        if (lines := block.splitlines()) and lines[0].startswith("event: ")
    ]


def names(stream: list[tuple[str, Any]]) -> list[str]:
    return [name for name, _ in stream]


async def test_knowledge_stream(seeded: Any) -> None:
    async with client(seeded) as api:
        stream = events(await api.post("/api/chat", json=QUESTION))
        second = events(await api.post("/api/chat", json=QUESTION))

    assert names(stream) == ["meta", *["token"] * 5, "citations", "done"]
    assert stream[0][1]["intent"] == "policy_question"
    assert "".join(payload["text"] for event, payload in stream if event == "token") == (
        "Unused items can be returned within 30 days. [1]"
    )
    assert stream[-2][1] == [
        {
            "n": 1,
            "heading_path": "Returns > Window",
            "section_id": "returns.window",
            "chunk_id": "chunk-1",
        }
    ]
    done = stream[-1][1]
    assert done["gate"]["passed"] is True
    assert done["trace"] == ["rewrite", "classify", "retrieve", "gate", "answer"]
    assert second[-1][1]["trace"] == ["rewrite", "classify", "fixed"]
    assert second[-1][1]["gate"] is None
    assert "usage" in done
    # The test fakes bypass LangChain callbacks; the ledger itself is unit-tested.
    assert isinstance(done["llm_calls"], int)
    assert "cost_usd" in done


@pytest.mark.parametrize("reason", ["low_evidence", "retrieval_error"])
async def test_knowledge_handoff(seeded: Any, reason: str) -> None:
    retriever = BrokenRetriever() if reason == "retrieval_error" else None
    async with client(seeded, score=0.01, retriever=retriever) as api:
        stream = events(await api.post("/api/chat", json=QUESTION))
    assert names(stream) == ["meta", "handoff", "done"]
    assert stream[1][1]["reason"] == reason
    assert stream[-1][1]["gate"]["passed"] is False
    assert stream[-1][1]["trace"] == ["rewrite", "classify", "retrieve", "gate", "handoff"]


@pytest.mark.parametrize("select_order", [True, False])
async def test_refund_interrupt_and_resume(seeded: Any, select_order: bool) -> None:
    async with client(seeded, refund=True) as api:
        initial = events(
            await api.post("/api/chat", json={**REQUEST, "message": "I want a refund"})
        )
        assert names(initial) == ["meta", "interrupt", "done"]
        picker = initial[1][1]
        assert picker["type"] == "order_picker"
        assert initial[-1][1]["gate"] is None
        _, service = seeded
        choices = service.list_recent_orders(REQUEST["customer_id"])
        assert [order["order_id"] for order in picker["orders"]] == [
            order.order_id for order in choices
        ]
        selected = refundable_order(service).order_id if select_order else "none"
        assert (
            await api.post(
                "/api/resume", json={**REQUEST, "customer_id": "CUST-0002", "value": selected}
            )
        ).status_code == 409
        resumed = events(await api.post("/api/resume", json={**REQUEST, "value": selected}))
        assert (
            await api.post("/api/resume", json={**REQUEST, "value": selected})
        ).status_code == 409

    assert names(resumed)[-1] == "done"
    trace = resumed[-1][1]["trace"]
    if select_order:
        assert trace == [
            "after_sales",
            "refund_identify",
            "refund_load",
            "refund_retrieve",
            "refund_decide",
            "refund_act",
        ]
        assert resumed[-2][0] == "citations"
        assert resumed[-2][1][0]["chunk_id"] == "refund-policy-1"
        assert "[1]" in "".join(data["text"] for event, data in resumed if event == "token")
    else:
        assert trace == ["after_sales", "refund_identify", "handoff"]
        assert names(resumed) == ["handoff", "done"]
        assert resumed[0][1]["reason"] == "order_not_found"


async def test_graph_exception_closes_stream(seeded: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: Any) -> None:
        raise RuntimeError("private error detail")

    monkeypatch.setattr(KnowledgePath, "gate", fail)
    async with client(seeded) as api, asyncio.timeout(5):
        response = await api.post("/api/chat", json=QUESTION)
        stream = events(response)
        assert (await api.post("/api/resume", json={**REQUEST, "value": "none"})).status_code == 409
    assert names(stream) == ["meta", "error", "handoff"]
    assert stream[1][1] == {"error_type": "RuntimeError"}
    assert stream[2][1]["reason"] == "system_error"
    assert "private error detail" not in response.text


async def test_resume_checkpoint_error_closes_stream(
    seeded: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from langgraph.graph.state import CompiledStateGraph

    def fail(self: Graph, *args: Any) -> None:
        raise RuntimeError("private checkpoint error")

    monkeypatch.setattr(CompiledStateGraph, "get_state", fail)
    async with client(seeded, refund=True) as api, asyncio.timeout(5):
        response = await api.post("/api/resume", json={**REQUEST, "value": "none"})
    stream = events(response)
    assert names(stream) == ["error", "handoff"]
    assert stream[0][1] == {"error_type": "RuntimeError"}
    assert stream[1][1]["reason"] == "system_error"
    assert "private checkpoint error" not in response.text


async def test_concurrent_turn_is_rejected(seeded: Any) -> None:
    entered = threading.Event()
    unblock = threading.Event()

    class BlockingRetriever(FixedRetriever):
        def retrieve(self, query: str, top_k: int) -> Any:
            entered.set()
            assert unblock.wait(timeout=5)
            return super().retrieve(query, top_k)

    async with client(seeded, retriever=BlockingRetriever(evidence(0.99))) as api:
        first = asyncio.create_task(api.post("/api/chat", json=QUESTION))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            assert (await api.post("/api/chat", json=QUESTION)).status_code == 409
        finally:
            unblock.set()
            assert names(events(await first))[-1] == "done"


async def test_request_validation(seeded: Any) -> None:
    settings, _ = seeded
    async with client(seeded) as api:
        for payload in [
            {"message": ""},
            {"message": "  "},
            {"message": "x" * (settings.api.max_message_chars + 1)},
            {"conversation_id": "ambiguous:id"},
        ]:
            assert (await api.post("/api/chat", json={**QUESTION, **payload})).status_code == 422
        assert (
            await api.post("/api/chat", json={**QUESTION, "customer_id": "missing"})
        ).status_code == 404
        assert (await api.post("/api/resume", json={**REQUEST, "value": "none"})).status_code == 409
        assert (
            await api.post(
                "/api/resume", json={**REQUEST, "value": "x" * (settings.api.max_resume_chars + 1)}
            )
        ).status_code == 422


@pytest.mark.parametrize("available", [True, False])
async def test_health_and_customers(seeded: Any, available: bool) -> None:
    def milvus() -> bool:
        if not available:
            raise ConnectionError
        return True

    async with client(seeded, milvus=milvus) as api:
        health = await api.get("/api/health")
        customers = await api.get("/api/customers")
        index = await api.get("/")
        assert (await api.get("/static/app.js")).status_code == 200
    assert health.status_code == customers.status_code == index.status_code == 200
    assert health.json() == {
        "status": "ok" if available else "degraded",
        "milvus": available,
        "order_db": True,
        "models_configured": True,
    }
    assert len(customers.json()) == seeded[0].api.demo_customer_limit
    assert all(set(customer) == {"customer_id", "name"} for customer in customers.json())


async def test_health_uses_effective_model_environment(
    seeded: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("LLM_FAST_MODEL", "fake-fast")
    monkeypatch.delenv("LLM_MAIN_MODEL", raising=False)
    async with client(seeded, configure_models=False) as api:
        missing = (await api.get("/api/health")).json()
        monkeypatch.setenv("LLM_MAIN_MODEL", "fake-main")
        configured = (await api.get("/api/health")).json()
    assert missing["models_configured"] is False
    assert missing["status"] == "degraded"
    assert configured["models_configured"] is True
    assert configured["status"] == "ok"


def test_token_chunks_preserve_exact_final_text() -> None:
    answer = " First  second\nthird [1]. "
    assert [event.data for event in events_for_update("answer", {"answer": answer}, 2)] == [
        {"text": " First  second\n"},
        {"text": "third [1]. "},
        [],
    ]
    assert names(
        [(event.name, event.data) for event in events_for_update("answer", {"answer": answer}, 1)]
    ) == ["token"] * 4 + ["citations"]


def test_nonterminal_updates_are_ignored() -> None:
    assert events_for_update("rewrite", {"answer": "", "handoff": None}, 2) == []
    assert events_for_update("tools", {"fallback_to_knowledge": True}, 2) == []
    assert events_for_update("retrieve", {"retrieval": evidence(0.99)}, 2) == []


def test_interrupt_mapping() -> None:
    picker = {"type": "order_picker", "orders": []}
    assert events_for_update("__interrupt__", picker, 2)[0].data == picker
