"""Order-tool answers may only state facts found in this turn's tool results."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from support_agent.graph.deps import GraphDeps
from support_agent.graph.handoff import HandoffReason
from support_agent.graph.nodes.tools_path import ToolsPath
from support_agent.graph.order_grounding import (
    OrderClaim,
    OrderGrounding,
    tool_data_text,
    ungrounded_claims,
)
from test_tool_paths import ToolFake, call, state


def test_quotes_match_tool_data_without_json_punctuation() -> None:
    data = tool_data_text({"get_order": {"order_id": "ORD-000115", "status": "shipped"}})
    decision = OrderGrounding(
        claims=[
            OrderClaim(claim="Order ORD-000115 has shipped.", quote="status: shipped"),
            OrderClaim(claim="It is ORD-000115.", quote="ORD-000115"),
            OrderClaim(claim="A friend may collect it.", quote=""),
            OrderClaim(claim="Bring photo ID.", quote="photo ID"),
            OrderClaim(claim="Partial id.", quote="ORD-00011"),
        ]
    )
    assert ungrounded_claims(decision, data) == [
        "A friend may collect it.",
        "Bring photo ID.",
        "Partial id.",
    ]


def _run(seeded: Any, grounding: Any, answer: str = "") -> tuple[dict[str, Any], ToolFake]:
    settings, service = seeded
    order = service.list_recent_orders("CUST-0001")[0]
    model = ToolFake(
        responses=[call(order_id=order.order_id), AIMessage(content=answer or order.status)],
        grounding=grounding,
    )
    result = ToolsPath(GraphDeps(settings, main_model=model, order_service=service))(state())
    return result, model


def test_policy_claim_without_order_quote_goes_to_gated_knowledge(seeded: Any) -> None:
    answer = "Yes, a friend can collect your parcel with photo ID."
    grounding = {"claims": [{"claim": answer, "quote": ""}]}
    result, model = _run(seeded, grounding, answer)
    assert result["fallback_to_knowledge"] is True
    assert "answer" not in result
    assert result["trace"][-2:] == ["ungrounded:1", "tools_fallback"]
    assert answer in str(model.grounding_seen[0][-1].content)


def test_order_fact_quoted_from_tool_data_is_released(seeded: Any) -> None:
    _, service = seeded
    order = service.list_recent_orders("CUST-0001")[0]
    grounding = {"claims": [{"claim": "Your order status.", "quote": order.order_id}]}
    result, _ = _run(seeded, grounding)
    assert result["answer"] == order.status
    assert "tools_fallback" not in result["trace"]


def test_grounding_checker_error_fails_closed(seeded: Any) -> None:
    result, _ = _run(seeded, RuntimeError("checker down"))
    assert result["fallback_to_knowledge"] is True
    assert "grounding_error" in result["trace"]
    assert "answer" not in result


def test_without_fallback_an_ungrounded_answer_hands_off(seeded: Any) -> None:
    settings, _ = seeded
    settings.agent.knowledge_fallback = False
    grounding = {"claims": [{"claim": "Store rule.", "quote": ""}]}
    result, _ = _run(seeded, grounding, "Store rule.")
    assert result["handoff"].reason == HandoffReason.INVALID_ANSWER
    assert "Store rule." not in result["answer"]


def test_grounding_off_keeps_the_old_release(seeded: Any) -> None:
    settings, _ = seeded
    settings.agent.order_grounding = False
    grounding = {"claims": [{"claim": "Store rule.", "quote": ""}]}
    result, model = _run(seeded, grounding, "Store rule.")
    assert result["answer"] == "Store rule."
    assert model.grounding_seen == []


def test_graph_sends_an_ungrounded_order_answer_through_the_gate(seeded: Any) -> None:
    from langchain_core.messages import HumanMessage

    from support_agent.graph.build import build_graph
    from support_agent.graph.intents import Intent
    from test_graph import fake
    from test_graph_knowledge import FixedRetriever, evidence

    settings, service = seeded
    settings.gate.threshold = 0.5
    answer = "Yes, a friend can collect your parcel; you have recent orders."
    model = ToolFake(
        responses=[call("list_recent_orders"), AIMessage(content=answer)],
        grounding={"claims": [{"claim": "A friend can collect it.", "quote": ""}]},
    )
    with GraphDeps(
        settings,
        fast_model=fake(Intent.SHIPPING_DELIVERY),
        main_model=model,
        order_service=service,
        retriever=FixedRetriever(evidence(0.01)),
    ) as deps:
        result = build_graph(deps).invoke(
            {
                "messages": [HumanMessage(content="Can a friend collect it?")],
                "customer_id": "CUST-0001",
            },
            {"configurable": {"thread_id": "CUST-0001:grounding"}},
        )
    trace = result["trace"]
    assert trace[:3] == ["rewrite", "classify", "tools"]
    assert trace[3].startswith("tool_call:list_recent_orders")
    assert trace[-5:] == ["ungrounded:1", "tools_fallback", "retrieve", "gate", "handoff"]
    assert result["handoff"].reason == HandoffReason.LOW_EVIDENCE
    assert "friend" not in result["answer"]
