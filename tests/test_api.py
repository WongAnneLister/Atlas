"""Offline coverage of public chat routes and graph event mapping."""

import asyncio
import json
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage

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
    readiness: Any = None,
    lock_store: Any = None,
    registry: Any = None,
    customer_id: str | None = REQUEST["customer_id"],
    root_path: str = "",
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
            retriever=RefundRetriever(
                text=f"{status.capitalize()} orders follow this final sale policy."
            ),
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
    app = create_app(
        ApiDeps(
            settings,
            deps,
            service,
            milvus,
            readiness=readiness,
            lock_store=lock_store,
            metrics_registry=registry,
        )
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, root_path=root_path),
            base_url=f"http://test{root_path}",
        ) as api,
    ):
        if customer_id is not None:
            api.headers.update(await session_header(api, customer_id))
        yield api


async def session_header(api: httpx.AsyncClient, customer_id: str) -> dict[str, str]:
    response = await api.post("/api/session", json={"customer_id": customer_id})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


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


@pytest.mark.parametrize("grounding", [False, True])
async def test_knowledge_stream(seeded: Any, monkeypatch, grounding: bool) -> None:
    from support_agent.reliability.llm_calls import ReliableModels
    from support_agent.reliability.structured import ParsedResponse

    seeded[0].grounding.enabled = grounding
    structured = ReliableModels.structured

    def fake_verifier(self, site, role, schema, messages, **kwargs):
        if site != "verify":
            return structured(self, site, role, schema, messages, **kwargs)
        [claim] = json.loads(messages[-1].content)
        [source] = claim["sources"]
        value = schema.model_validate(
            {
                "verdicts": [
                    {
                        "number": claim["number"],
                        "verdict": "supported",
                        "evidence": [{"source": source["n"], "quote": source["text"]}],
                    }
                ]
            }
        )
        return ParsedResponse(value, "fixture"), None

    monkeypatch.setattr(ReliableModels, "structured", fake_verifier)
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
    assert done["trace"] == [
        "input_guard",
        "rewrite",
        "classify",
        "retrieve",
        "gate",
        "answer",
        *(["ground"] if grounding else []),
        "output_guard",
    ]
    assert second[-1][1]["trace"] == ["input_guard", "rewrite", "classify", "fixed", "output_guard"]
    assert second[-1][1]["gate"] is None
    assert "usage" in done
    # The test fakes bypass LangChain callbacks; the ledger itself is unit-tested.
    assert isinstance(done["llm_calls"], int)
    assert "cost_usd" in done


@pytest.mark.parametrize("reason", ["low_evidence", "dependency_unavailable"])
async def test_knowledge_handoff(seeded: Any, reason: str) -> None:
    retriever = BrokenRetriever() if reason == "dependency_unavailable" else None
    async with client(seeded, score=0.01, retriever=retriever) as api:
        stream = events(await api.post("/api/chat", json=QUESTION))
    assert names(stream) == ["meta", "handoff", "done"]
    assert stream[1][1]["reason"] == reason
    assert stream[-1][1]["gate"]["passed"] is False
    assert stream[-1][1]["trace"] == [
        "input_guard",
        "rewrite",
        "classify",
        "retrieve",
        "gate",
        "handoff",
        "output_guard",
    ]


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
                "/api/resume",
                json={**REQUEST, "value": selected},
                headers=await session_header(api, "CUST-0002"),
            )
        ).status_code == 409
        resumed = events(
            await api.post(
                "/api/resume", json={**REQUEST, "customer_id": "CUST-0002", "value": selected}
            )
        )
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
            "output_guard",
        ]
        assert resumed[-2][0] == "citations"
        assert resumed[-2][1][0]["chunk_id"] == "refund-policy-1"
        assert "[1]" in "".join(data["text"] for event, data in resumed if event == "token")
    else:
        assert trace == ["after_sales", "refund_identify", "handoff", "output_guard"]
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
            second = await api.post("/api/chat", json=QUESTION)
            assert second.status_code == 409
            assert second.json()["detail"] == "Still answering your previous message. Please wait."
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
        assert (await api.post("/api/session", json={"customer_id": "missing"})).status_code == 403
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
    assert [event.data for event in events_for_update("output_guard", {"answer": answer}, 2)] == [
        {"text": " First  second\n"},
        {"text": "third [1]. "},
        [],
    ]
    assert names(
        [
            (event.name, event.data)
            for event in events_for_update("output_guard", {"answer": answer}, 1)
        ]
    ) == ["token"] * 4 + ["citations"]


def test_nonterminal_updates_are_ignored() -> None:
    assert events_for_update("rewrite", {"answer": "", "handoff": None}, 2) == []
    assert events_for_update("tools", {"fallback_to_knowledge": True}, 2) == []
    assert events_for_update("retrieve", {"retrieval": evidence(0.99)}, 2) == []


def test_interrupt_mapping() -> None:
    picker = {"type": "order_picker", "orders": []}
    assert events_for_update("__interrupt__", picker, 2)[0].data == picker


async def test_unchecked_reply_never_reaches_the_stream(
    seeded: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    pending = "Please contact witness@example.com."

    def candidate(self, state):
        assert state.gate.passed
        return {
            "answer": pending,
            "messages": [AIMessage(content=pending)],
            "trace": [*state.trace, "answer"],
        }

    monkeypatch.setattr(KnowledgePath, "answer", candidate)
    async with client(seeded) as api:
        stream = events(await api.post("/api/chat", json=QUESTION))
    assert names(stream) == ["meta", "handoff", "done"]
    assert stream[1][1]["reason"] == "guardrail_blocked"
    assert stream[-1][1]["trace"][-2:] == ["answer", "output_guard"]
    assert pending not in str(stream)


def test_partial_answer_publishes_citations_and_targeted_handoff() -> None:
    from types import SimpleNamespace

    answer = "The return window is 30 days. [2]"
    summary = "I will pass this question to a human support agent: “Can I pay with gold?”"
    citation = {"n": 2, "chunk_id": "window", "section_id": "returns", "heading_path": "Returns"}
    events = events_for_update(
        "output_guard",
        {
            "answer": answer + "\n\n" + summary,
            "citations": [citation],
            "handoff": SimpleNamespace(
                reason="unsupported_part", trace_id="trace", customer_message=summary
            ),
        },
        10,
    )
    assert [event.name for event in events] == ["token", "citations", "handoff"]
    assert events[0].data == {"text": answer}
    assert events[1].data == [citation]
    assert events[2].data == {
        "reason": "unsupported_part",
        "message": summary,
        "trace_id": "trace",
    }
