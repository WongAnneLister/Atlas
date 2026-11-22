from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from langgraph.types import Command
from pydantic import Field

from retrieval_fakes import LegacyFilterSupport
from support_agent.config import Settings
from support_agent.graph.build import build_graph
from support_agent.graph.deps import GraphDeps
from support_agent.graph.intents import Intent
from support_agent.graph.refund_decision import RefundDecision
from support_agent.orders.fixtures import TIME_SENSITIVE_CUSTOMER
from support_agent.orders.models import Order
from support_agent.orders.service import OrderService
from support_agent.retrieval.filters import RetrievalFilters
from support_agent.retrieval.types import RetrievedChunk
from test_graph import StructuredFake


class DecisionFake(FakeListChatModel):
    decisions: list[Any] = Field(default_factory=list)
    decision_calls: int = 0
    decision_prompt: str = ""

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        assert issubclass(schema, RefundDecision)
        assert kwargs == {"include_raw": True}

        def decide(messages: Any) -> dict[str, Any]:
            self.decision_calls += 1
            self.decision_prompt = messages[-1].content
            value = self.decisions.pop(0)
            if isinstance(value, Exception):
                raise value
            return {
                "parsed": value,
                "raw": AIMessage(content="", response_metadata={"model_name": "fake-main"}),
                "parsing_error": None,
            }

        return RunnableLambda(decide)


class FixedRetriever(LegacyFilterSupport):
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


class PolicyVersionRetriever(FixedRetriever):
    def __init__(self, *, empty: bool = False) -> None:
        super().__init__()
        self.empty = empty
        self.calls: list[RetrievalFilters | None] = []

    def supports_filters(self) -> bool:
        return True

    def retrieve(
        self, query: str, top_k: int, filters: RetrievalFilters | None = None
    ) -> list[RetrievedChunk]:
        self.calls.append(filters)
        base = super().retrieve(query, top_k)[0]
        change = date(2026, 9, 1)
        versions = [
            base.model_copy(
                update={
                    "chunk_id": "old",
                    "section_id": "returns.policy@2026-01-01",
                    "doc_type": "policy",
                    "text": "You can return products within 90 days of purchase.",
                    "effective_from": date(2026, 1, 1),
                    "effective_to": change,
                }
            ),
            base.model_copy(
                update={
                    "chunk_id": "current",
                    "section_id": "returns.policy",
                    "doc_type": "policy",
                    "text": "You can return products within 30 days of purchase.",
                    "effective_from": change,
                    "effective_to": None,
                }
            ),
        ]
        if self.empty:
            return []
        return [chunk for chunk in versions if filters is None or filters.matches(chunk)]


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


@pytest.mark.parametrize(
    ("order_id", "stored_date", "version", "window"),
    [
        ("ORD-999996", date(2026, 8, 20), "old", 90),
        ("ORD-999998", date(2026, 9, 1), "current", 30),
    ],
)
def test_refund_uses_verified_order_date_and_explains_historical_citation(
    seeded: Any, order_id: str, stored_date: date, version: str, window: int
) -> None:
    settings, service = seeded
    customer = TIME_SENSITIVE_CUSTOMER.customer_id
    order = service.get_order(order_id, customer)
    decision = (
        yes_decision(order)
        if version == "old"
        else {
            "eligible": "no",
            "reasons": ["The order is outside the 30-day return window [1]."],
            "citations": [1],
        }
    )
    main = DecisionFake(responses=["unused"], decisions=[decision])
    retriever = PolicyVersionRetriever()
    with deps(settings, service, main, retriever) as graph_deps:
        result = build_graph(graph_deps).invoke(
            {
                "messages": [
                    HumanMessage(content=f"I bought it in August. Please refund {order_id}.")
                ],
                "customer_id": customer,
            },
            {"configurable": {"thread_id": "refund-version"}},
        )
    assert len(retriever.calls) == 1
    filters = retriever.calls[0]
    assert filters is not None
    assert filters.as_of == stored_date == order.order_date
    assert filters.product_category is None
    assert result["filters"] == filters
    assert result["filters_applied"] is True
    assert result["trace"] == [
        "input_guard",
        "rewrite",
        "classify",
        "after_sales",
        "refund_identify",
        "refund_load",
        "refund_retrieve",
        "refund_decide",
        "refund_act",
        "output_guard",
    ]
    assert [chunk.chunk_id for chunk in result["retrieval"]] == [version]
    assert result["citations"][0]["chunk_id"] == version
    assert f"within {window} days" in main.decision_prompt
    assert result["output_guard_flag"] is None
    if version == "old":
        assert "Validity from 2026-01-01 until 2026-09-01 (end excluded)." in main.decision_prompt
        assert result["answer"].startswith(
            "Your order was placed on 2026-08-20. "
            "The policy that applied then was in effect from 2026-01-01 "
            "until 2026-09-01 [1]."
        )
        assert result["refund_request"]["status"] == "pending_review"
    else:
        assert "Validity from 2026-09-01." in main.decision_prompt
        assert result["answer"].startswith("I cannot approve this request.")


def test_empty_order_date_filter_hands_off_without_decision_or_unfiltered_retry(
    seeded: Any,
) -> None:
    settings, service = seeded
    main = DecisionFake(responses=["unused"])
    retriever = PolicyVersionRetriever(empty=True)
    with deps(settings, service, main, retriever) as graph_deps:
        result = invoke(build_graph(graph_deps), "Refund ORD-000001. I bought it in August.")
    assert result["trace"] == [
        "input_guard",
        "rewrite",
        "classify",
        "after_sales",
        "refund_identify",
        "refund_load",
        "refund_retrieve",
        "handoff",
        "output_guard",
    ]
    assert main.decision_calls == 0
    assert result["gate"].reason == "empty_retrieval"
    assert result["handoff"].reason == "low_evidence"
    assert len(retriever.calls) == 1
    assert retriever.calls[0] is not None
    assert result["filters"] == result["handoff"].filters == retriever.calls[0]
    assert result["filters_applied"] is result["handoff"].filters_applied is True


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
        "input_guard",
        "rewrite",
        "classify",
        "after_sales",
        "refund_identify",
        "refund_load",
        "refund_retrieve",
        "refund_decide",
        "refund_act",
        "output_guard",
    ]
    assert result["refund_request"]["status"] == "pending_review"
    assert result["refund_request"]["order_id"] == "ORD-000001"
    assert main.decision_calls == 1
    with service.repository.connection() as connection:
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM refund_requests").fetchone()[0] == 1


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
    assert result["trace"][-2:] == ["handoff", "output_guard"]
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
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM refund_requests").fetchone()[0] == 0


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


def test_item_with_a_pending_request_is_not_requested_again(seeded: Any) -> None:
    settings, service = seeded
    order = service.get_order("ORD-000001", "CUST-0001")
    item = order.items[0].item_id
    service.create_refund_request(
        order.order_id, order.customer_id, [item], "Earlier", idempotency_key="earlier-chat"
    )
    main = DecisionFake(responses=["unused"], decisions=[yes_decision(order)])
    with deps(settings, service, main) as graph_deps:
        result = invoke(build_graph(graph_deps), "Refund ORD-000001", thread="later-chat")
    assert result["trace"][-4:] == ["refund_retrieve", "refund_decide", "handoff", "output_guard"]
    assert result["order_context"]["pending_refund_item_ids"] == [item]
    assert result["handoff"].reason.value == "policy_requires_human"
    assert result.get("refund_request") is None
    with service.repository.connection() as connection:
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM refund_requests").fetchone()[0] == 1


def test_write_guard_holds_when_the_pending_read_was_stale(seeded: Any, monkeypatch) -> None:
    settings, service = seeded
    order = service.get_order("ORD-000001", "CUST-0001")
    service.create_refund_request(
        order.order_id, order.customer_id, [order.items[0].item_id], "Earlier"
    )
    # Simulate another conversation writing after this one loaded the order.
    monkeypatch.setattr(service, "pending_refund_item_ids", lambda *_, **__: [])
    main = DecisionFake(responses=["unused"], decisions=[yes_decision(order)])
    with deps(settings, service, main) as graph_deps:
        result = invoke(build_graph(graph_deps), "Refund ORD-000001", thread="racing-chat")
    assert result["trace"][-3:] == ["refund_decide", "handoff", "output_guard"]
    assert result["handoff"].reason.value == "policy_requires_human"
    assert result.get("refund_request") is None
    with service.repository.connection() as connection:
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM refund_requests").fetchone()[0] == 1


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
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM refund_requests").fetchone()[0] == 0


@pytest.mark.integration
def test_postgres_checkpoint_survives_refund_restart(postgres_database, seeded) -> None:
    from pydantic import SecretStr

    from support_agent.db.migrate import upgrade
    from support_agent.gate.evidence import GateResult
    from support_agent.graph.postgres import postgres_saver
    from support_agent.orders.seed import seed_orders

    settings, url = postgres_database
    local, _ = seeded
    settings.orders = local.orders
    settings.data = local.data
    settings.database_url = SecretStr(url.render_as_string(hide_password=False))
    service = OrderService(platform=settings)
    config = {"configurable": {"thread_id": "restart-picker"}}
    try:
        upgrade(service.repository.engine)
        seed_orders(settings)
        with postgres_saver(settings) as saver:
            saver.setup()
        with deps(settings, service, DecisionFake(responses=["unused"])) as before:
            first = build_graph(before)
            paused = first.invoke(
                {
                    "messages": [HumanMessage(content="Please refund my order")],
                    "customer_id": "CUST-0001",
                },
                config,
                durability="sync",
            )
            picker = paused["__interrupt__"][0].value
            assert picker["type"] == "order_picker"
            turn_id = paused["messages"][-1].id
            assert turn_id

        orders = [service.get_order(choice["order_id"], "CUST-0001") for choice in picker["orders"]]
        order = next(order for order in orders if order.items[0].refunded_quantity == 0)
        status = order.status.value.replace("_", " ")
        policy = FixedRetriever(text=f"{status} refund policy for final sale.")
        model = DecisionFake(responses=["unused"], decisions=[yes_decision(order)])
        with deps(settings, service, model, policy) as after:
            second = build_graph(after)
            restored = second.get_state(config)
            assert restored.interrupts[0].value == picker
            assert restored.values["messages"][-1].id == turn_id
            result = second.invoke(Command(resume=order.order_id), config, durability="sync")
            assert result["trace"] == [
                "input_guard",
                "rewrite",
                "classify",
                "after_sales",
                "refund_identify",
                "refund_load",
                "refund_retrieve",
                "refund_decide",
                "refund_act",
                "output_guard",
            ]
            assert result["refund_request"]["order_id"] == order.order_id

        with deps(settings, service, DecisionFake(responses=["unused"])) as reader:
            persisted = build_graph(reader).get_state(config).values
            assert isinstance(persisted["gate"], GateResult)
            assert isinstance(persisted["retrieval"][0], RetrievedChunk)
            assert persisted["order_context"] == result["order_context"]
            assert persisted["refund_request"] == result["refund_request"]
    finally:
        service.close()
