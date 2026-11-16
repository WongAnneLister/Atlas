from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from langgraph.types import Command
from pydantic import Field

from support_agent.config import Settings
from support_agent.graph.build import build_graph
from support_agent.graph.deps import GraphDeps
from support_agent.graph.intents import Intent
from support_agent.graph.nodes.refund import RefundDecision
from support_agent.orders.models import Order
from support_agent.orders.service import OrderService
from support_agent.retrieval.types import RetrievedChunk
from test_graph import StructuredFake


class DecisionFake(FakeListChatModel):
    decisions: list[Any] = Field(default_factory=list)
    decision_calls: int = 0

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        assert schema is RefundDecision
        assert kwargs == {"include_raw": True}

        def decide(messages: Any) -> dict[str, Any]:
            self.decision_calls += 1
            value = self.decisions.pop(0)
            if isinstance(value, Exception):
                raise value
            return {
                "parsed": value,
                "raw": AIMessage(content="", response_metadata={"model_name": "fake-main"}),
                "parsing_error": None,
            }

        return RunnableLambda(decide)


class FixedRetriever:
    def __init__(self, score: float = 0.99, text: str = "Refund and return policy.") -> None:
        self.score = score
        self.text = text

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        return [
            RetrievedChunk(
                chunk_id="refund-policy-1",
                doc_id="refunds",
                section_id="refunds.policy",
                title="Refund policy",
                heading_path="Refunds > Policy",
                text=self.text,
                n_tokens=5,
                scores={"rerank": self.score},
            )
        ][:top_k]


def fast(intent: Intent = Intent.REFUND_REQUEST) -> StructuredFake:
    return StructuredFake(
        responses=["unused"],
        predictions=[{"intent": intent, "confidence": 0.99}],
    )


def invoke(graph: Any, question: str, thread: str = "refund") -> dict[str, Any]:
    return graph.invoke(
        {"messages": [HumanMessage(content=question)], "customer_id": "CUST-0001"},
        {"configurable": {"thread_id": thread}},
    )


def deps(
    settings: Settings,
    service: OrderService,
    main: DecisionFake,
    retriever: FixedRetriever | None = None,
) -> GraphDeps:
    settings.gate.threshold = 0.5
    return GraphDeps(
        settings,
        fast_model=fast(),
        main_model=main,
        retriever=retriever or FixedRetriever(),
        order_service=service,
    )


def yes_decision(order: Order) -> dict[str, Any]:
    return {
        "eligible": "yes",
        "items": [order.items[0].item_id],
        "reasons": ["The policy supports this request [1]."],
        "citations": [1],
    }


def test_act_returns_citations_for_refund_denial() -> None:
    from support_agent.graph.nodes.refund import RefundPath
    from support_agent.graph.state import CitationRecord, ConversationState

    chunks = FixedRetriever().retrieve("refunds", 1)
    state = ConversationState(
        retrieval=chunks,
        refund_decision={"eligible": "no", "reasons": ["Final sale [1]."], "citations": [1]},
    )
    result = RefundPath(GraphDeps(Settings())).act(state)
    assert result["trace"] == ["refund_act"]
    assert result["citations"] == [
        CitationRecord(
            n=1,
            chunk_id=chunks[0].chunk_id,
            section_id=chunks[0].section_id,
            heading_path=chunks[0].heading_path,
        )
    ]


def test_direct_order_yes_creates_one_pending_request(seeded: Any) -> None:
    settings, service = seeded
    order = service.get_order("ORD-000001", "CUST-0001")
    main = DecisionFake(responses=["unused"], decisions=[yes_decision(order)])
    with deps(settings, service, main) as graph_deps:
        result = invoke(build_graph(graph_deps), "I want a refund for ORD-000001")
    assert result["trace"] == [
        "rewrite",
        "classify",
        "after_sales",
        "refund_identify",
        "refund_load",
        "refund_retrieve",
        "refund_decide",
        "refund_act",
    ]
    assert result["refund_request"]["status"] == "pending_review"
    assert result["refund_request"]["order_id"] == "ORD-000001"
    assert main.decision_calls == 1
    with service.repository.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM refund_requests").fetchone()[0] == 1


def test_fast_order_extraction_verifies_model_returned_id(seeded: Any) -> None:
    settings, service = seeded
    order = service.get_order("ORD-000001", "CUST-0001")
    main = DecisionFake(responses=["unused"], decisions=[yes_decision(order)])
    fast_model = StructuredFake(
        responses=["ORD-000001"],
        predictions=[{"intent": Intent.REFUND_REQUEST, "confidence": 0.99}],
    )
    with GraphDeps(
        settings,
        fast_model=fast_model,
        main_model=main,
        retriever=FixedRetriever(),
        order_service=service,
        allow_untuned_gate=True,
    ) as graph_deps:
        result = invoke(build_graph(graph_deps), "Please refund the order in my account")
    assert result["refund_request"]["order_id"] == "ORD-000001"


def test_missing_order_interrupts_then_resume_continues(seeded: Any) -> None:
    settings, service = seeded
    main = DecisionFake(responses=["unused"], decisions=[])
    with deps(settings, service, main) as graph_deps:
        graph = build_graph(graph_deps)
        config = {"configurable": {"thread_id": "picker"}}
        paused = graph.invoke(
            {
                "messages": [HumanMessage(content="I want a refund for my last order")],
                "customer_id": "CUST-0001",
            },
            config,
        )
        assert paused["__interrupt__"][0].value["type"] == "order_picker"
        assert paused["__interrupt__"][0].value["orders"]
        choices = paused["__interrupt__"][0].value["orders"]
        selected_id = next(
            choice["order_id"]
            for choice in choices
            if any(
                item.refunded_quantity < item.quantity
                for item in service.get_order(choice["order_id"], "CUST-0001").items
            )
        )
        selected_order = service.get_order(selected_id, "CUST-0001")
        policy = f"{selected_order.status.value} refund policy."
        if any(item.final_sale for item in selected_order.items):
            policy += " Final sale items require review."
        graph_deps.retriever.text = policy
        main.decisions.append(yes_decision(selected_order))
        result = graph.invoke(Command(resume=selected_id), config)
    assert result["refund_request"]["order_id"] == selected_id
    assert main.decision_calls == 1


def test_picker_none_hands_off_without_decision(seeded: Any) -> None:
    settings, service = seeded
    main = DecisionFake(responses=["unused"], decisions=[])
    with deps(settings, service, main) as graph_deps:
        graph = build_graph(graph_deps)
        config = {"configurable": {"thread_id": "none"}}
        graph.invoke(
            {
                "messages": [HumanMessage(content="Please refund my order")],
                "customer_id": "CUST-0001",
            },
            config,
        )
        result = graph.invoke(Command(resume="none"), config)
    assert result["handoff"].reason.value == "order_not_found"
    assert main.decision_calls == 0


def test_foreign_order_is_not_leaked_and_invalid_picker_choice_hands_off(seeded: Any) -> None:
    settings, service = seeded
    foreign = service.list_recent_orders("CUST-0002", limit=1)[0].order_id
    main = DecisionFake(responses=["unused"], decisions=[])
    with deps(settings, service, main) as graph_deps:
        graph = build_graph(graph_deps)
        config = {"configurable": {"thread_id": "foreign"}}
        paused = graph.invoke(
            {"messages": [HumanMessage(content=f"Refund {foreign}")], "customer_id": "CUST-0001"},
            config,
        )
        orders = paused["__interrupt__"][0].value["orders"]
        assert foreign not in {item["order_id"] for item in orders}
        result = graph.invoke(Command(resume=foreign), config)
    assert result["handoff"].reason.value == "order_not_found"
    assert main.decision_calls == 0


def test_policy_gate_failure_skips_decision_model(seeded: Any) -> None:
    settings, service = seeded
    main = DecisionFake(responses=["unused"], decisions=[])
    with deps(settings, service, main, FixedRetriever(score=0.01)) as graph_deps:
        result = invoke(build_graph(graph_deps), "Refund ORD-000001")
    assert result["handoff"].reason.value == "low_evidence"
    assert result["trace"][-1] == "handoff"
    assert main.decision_calls == 0


def test_final_sale_yes_without_final_sale_policy_becomes_human(seeded: Any) -> None:
    settings, service = seeded
    order = service.get_order("ORD-000005", "CUST-0001")
    main = DecisionFake(responses=["unused"], decisions=[yes_decision(order)])
    with deps(settings, service, main) as graph_deps:
        result = invoke(build_graph(graph_deps), "Refund ORD-000005")
    assert result["handoff"].reason.value == "policy_requires_human"
    assert result.get("refund_request") is None
    with service.repository.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM refund_requests").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("order_id", "policy_text", "eligible", "expected"),
    [
        ("ORD-000001", "Refund and return policy.", "yes", "request"),
        ("ORD-000005", "Refund and return policy.", "yes", "handoff"),
        ("ORD-000008", "Refund and return policy.", "yes", "handoff"),
        ("ORD-000008", "Cancelled orders can receive refunds.", "yes", "request"),
        ("ORD-000001", "Refund and return policy.", "no", "answer"),
    ],
)
def test_seed_edge_order_decisions_are_checked_before_action(
    seeded: Any, order_id: str, policy_text: str, eligible: str, expected: str
) -> None:
    settings, service = seeded
    order = service.get_order(order_id, "CUST-0001")
    main = DecisionFake(
        responses=["unused"],
        decisions=[
            {
                "eligible": eligible,
                "items": [order.items[0].item_id] if eligible == "yes" else [],
                "reasons": ["The policy supports this request [1]."],
                "citations": [1],
            }
        ],
    )
    with deps(settings, service, main, FixedRetriever(text=policy_text)) as graph_deps:
        result = invoke(build_graph(graph_deps), f"Refund {order_id}")
    if expected == "request":
        assert result["refund_request"]["status"] == "pending_review"
    elif expected == "handoff":
        assert result["handoff"].reason.value == "policy_requires_human"
        assert result.get("refund_request") is None
    else:
        assert "ask a human agent" in result["answer"]
        assert result.get("refund_request") is None


@pytest.mark.parametrize("eligible", ["no", "needs_human"])
def test_no_or_uncertain_decision_creates_no_request(seeded: Any, eligible: str) -> None:
    settings, service = seeded
    main = DecisionFake(
        responses=["unused"],
        decisions=[
            {
                "eligible": eligible,
                "items": [],
                "reasons": ["The policy does not support this request [1]."],
                "citations": [1],
            }
        ],
    )
    with deps(settings, service, main) as graph_deps:
        result = invoke(build_graph(graph_deps), "Refund ORD-000001")
    if eligible == "needs_human":
        assert result["handoff"].reason.value == "policy_requires_human"
    else:
        assert "cannot approve" in result["answer"]
    with service.repository.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM refund_requests").fetchone()[0] == 0
