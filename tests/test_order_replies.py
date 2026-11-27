"""Template mode: the order model picks lookups and decides; code writes the reply."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from support_agent.graph.deps import GraphDeps
from support_agent.graph.handoff import HandoffReason
from support_agent.graph.nodes.tools_path import ToolsPath
from support_agent.graph.order_replies import render_order_reply
from test_tool_paths import ToolFake, call, state

ORDER = {
    "order_id": "ORD-1",
    "status": "partially_refunded",
    "order_date": "2026-10-29",
    "delivered_at": "2026-11-04",
    "currency": "USD",
    "total": "617.11",
    "coupon_code": "DEMO10",
    "items": [
        {
            "quantity": 3,
            "name": "Philips 27E1",
            "model": "27E1",
            "unit_price": "195.24",
            "refunded_quantity": 1,
            "final_sale": False,
        },
        {
            "quantity": 1,
            "name": "Philips BHD",
            "model": "BHD340/10",
            "unit_price": "31.39",
            "refunded_quantity": 0,
            "final_sale": True,
        },
    ],
}
TRACKING = {
    "order_id": "ORD-1",
    "carrier": "Mock Carrier",
    "tracking_number": "MOCK-1",
    "status": "in_transit",
    "shipped_at": "2026-11-02",
    "expected_delivery": "2026-11-12",
    "last_event_at": "2026-11-09T00:00:00Z",
    "last_event": "Shipment accepted.",
}


def reply(decision: bool, text: str = "") -> AIMessage:
    return AIMessage(
        content=text,
        tool_calls=[
            {
                "name": "reply",
                "args": {"answer_from_order_data": decision},
                "id": "r",
                "type": "tool_call",
            }
        ],
    )


def test_render_states_only_tool_values() -> None:
    text = render_order_reply(
        [
            ("get_order", "ORD-1", ORDER),
            ("get_tracking", "ORD-1", TRACKING),
            ("get_order", "ORD-1", ORDER),
        ]
    )
    assert text.count("Order ORD-1") == 1
    assert "partially refunded" in text
    assert "Delivered on 2026-11-04." in text
    assert "Coupon used: DEMO10." in text
    assert "- 3 x Philips 27E1 (27E1), 195.24 USD each, 1 refunded" in text
    assert "- 1 x Philips BHD (BHD340/10), 31.39 USD each, final sale" in text
    assert "tracking number MOCK-1. Status: in transit." in text
    assert "Estimated delivery: 2026-11-12." in text
    assert "Last update on 2026-11-09: Shipment accepted." in text


def test_render_lists_orders_and_asks_to_pick_only_when_nothing_else_was_read() -> None:
    recent = [{**ORDER, "status": "shipped"}]
    alone = render_order_reply([("list_recent_orders", None, recent)])
    assert "- ORD-1 (placed 2026-10-29): shipped, total 617.11 USD" in alone
    assert "Tell me the order id" in alone
    both = render_order_reply(
        [("list_recent_orders", None, recent), ("get_tracking", "ORD-1", None)]
    )
    assert "Tell me the order id" not in both
    assert "There is no shipment tracking for ORD-1 yet." in both


def _run(seeded: Any, *responses: AIMessage) -> tuple[dict[str, Any], ToolFake]:
    settings, service = seeded
    settings.agent.order_replies = "template"
    model = ToolFake(responses=list(responses))
    result = ToolsPath(GraphDeps(settings, main_model=model, order_service=service))(state())
    return result, model


def _order_id(seeded: Any) -> str:
    return seeded[1].list_recent_orders("CUST-0001")[0].order_id


def test_reply_is_rendered_and_model_text_is_never_released(seeded: Any) -> None:
    order_id = _order_id(seeded)
    invented = "A friend can collect it with photo ID."
    result, model = _run(seeded, call(order_id=order_id), reply(True, invented))
    assert invented not in result["answer"]
    assert result["answer"].startswith(f"Order {order_id}")
    assert result["trace"][-1] == "reply:order_data"
    assert "reply" in [tool.name for tool in model.schemas]
    assert model.grounding_seen == []


def test_question_not_answered_by_order_data_goes_to_gated_knowledge(seeded: Any) -> None:
    result, _ = _run(seeded, call("list_recent_orders"), reply(False, "Yes, a friend can."))
    assert result["fallback_to_knowledge"] is True
    assert "answer" not in result
    assert result["trace"][-2:] == ["reply:not_order_data", "tools_fallback"]


def test_plain_text_gets_one_reminder_then_fails_closed(seeded: Any) -> None:
    order_id = _order_id(seeded)
    result, model = _run(
        seeded, call(order_id=order_id), AIMessage(content="It shipped."), reply(True)
    )
    assert "reply_reminder" in result["trace"]
    assert isinstance(model.seen[-1][-1], HumanMessage)
    assert result["trace"][-1] == "reply:order_data"
    twice, _ = _run(seeded, call(order_id=order_id), AIMessage(content="a"), AIMessage(content="b"))
    assert twice["fallback_to_knowledge"] is True
    assert "answer" not in twice


def test_reply_without_a_successful_lookup_hands_off(seeded: Any) -> None:
    result, _ = _run(seeded, call(order_id="ORD-999999"), reply(True))
    assert result["handoff"].reason == HandoffReason.ORDER_NOT_FOUND


def test_graph_routes_a_policy_question_from_the_order_path_through_the_gate(
    seeded: Any,
) -> None:
    from support_agent.graph.build import build_graph
    from support_agent.graph.intents import Intent
    from test_graph import fake
    from test_graph_knowledge import FixedRetriever, evidence

    settings, service = seeded
    settings.agent.order_replies = "template"
    settings.gate.threshold = 0.5
    model = ToolFake(responses=[call("list_recent_orders"), reply(False, "Yes, a friend can.")])
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
            {"configurable": {"thread_id": "CUST-0001:template"}},
        )
    trace = result["trace"]
    assert trace[:4] == ["input_guard", "rewrite", "classify", "tools"]
    assert trace[-6:] == [
        "reply:not_order_data",
        "tools_fallback",
        "retrieve",
        "gate",
        "handoff",
        "output_guard",
    ]
    assert result["handoff"].reason == HandoffReason.LOW_EVIDENCE
    assert "friend" not in result["answer"]


def test_a_reply_with_no_lookup_this_turn_gets_one_chance_to_read_the_order(
    seeded: Any,
) -> None:
    # "Which order were we discussing?": the model knows the id from earlier turns but
    # replies before reading it again. One reminder, then the normal lookup and reply.
    order_id = _order_id(seeded)
    result, model = _run(seeded, reply(True), call(order_id=order_id), reply(True))
    assert "relookup_reminder" in result["trace"]
    assert result["trace"][-1] == "reply:order_data"
    assert result["answer"].startswith(f"Order {order_id}")
    assert "earlier in this conversation" in str(model.seen[1][-1].content)


def test_a_second_reply_without_a_lookup_still_hands_off(seeded: Any) -> None:
    result, _ = _run(seeded, reply(True), reply(True))
    assert result["trace"].count("relookup_reminder") == 1
    assert result["handoff"].reason == HandoffReason.TOOL_ERROR


def test_the_relookup_switch_restores_the_old_handoff(seeded: Any) -> None:
    seeded[0].agent.order_relookup = False
    result, _ = _run(seeded, reply(True), call(order_id=_order_id(seeded)), reply(True))
    assert "relookup_reminder" not in result["trace"]
    assert result["handoff"].reason == HandoffReason.TOOL_ERROR
