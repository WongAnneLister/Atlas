"""Offline order loops, ownership isolation, handoffs and fixed replies."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableLambda
from pydantic import Field

from support_agent.config import Settings
from support_agent.graph.build import build_graph
from support_agent.graph.deps import GraphDeps
from support_agent.graph.handoff import HandoffPayload, HandoffReason, make_handoff
from support_agent.graph.intents import Intent
from support_agent.graph.nodes.complaint import ComplaintPath
from support_agent.graph.nodes.fixed import fixed_reply
from support_agent.graph.nodes.tools_path import ToolsPath
from support_agent.graph.state import ConversationState
from support_agent.graph.tools import build_order_tools
from test_graph import fake


class ToolFake(FakeMessagesListChatModel):
    seen: list[Any] = Field(default_factory=list)
    schemas: list[Any] = Field(default_factory=list)

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        self.schemas = tools

        def invoke(messages: Any) -> Any:
            self.seen.append(list(messages))
            return self.invoke(messages)

        return RunnableLambda(invoke)


def call(name: str = "get_order", **args: Any) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": "lookup", "type": "tool_call"}],
    )


def state(intent: Intent = Intent.ORDER_STATUS, question: str = "my order") -> ConversationState:
    return ConversationState(
        messages=[HumanMessage(content=question)],
        rewritten_query=question,
        customer_id="CUST-0001",
        intent=intent,
    )


def test_graph_order_status_has_tool_trace_and_database_status(seeded: Any) -> None:
    settings, service = seeded
    order = service.list_recent_orders("CUST-0001")[0]
    model = ToolFake(responses=[call(order_id=order.order_id), AIMessage(content=order.status)])
    with GraphDeps(
        settings, fast_model=fake(Intent.ORDER_STATUS), main_model=model, order_service=service
    ) as deps:
        result = build_graph(deps).invoke(
            {
                "messages": [HumanMessage(content=f"Where is {order.order_id}?")],
                "customer_id": "CUST-0001",
            },
            {"configurable": {"thread_id": "CUST-0001:order"}},
        )
    assert result["trace"][:3] == ["rewrite", "classify", "tools"]
    assert result["trace"][3].startswith("tool_call:get_order:")
    assert result["trace"][4].startswith("tool_result:get_order:")
    assert result["answer"] == order.status
    assert result["order_context"]["get_order"]["status"] == order.status
    assert result["agent_steps"] == 2
    assert result["handoff"] is None
    assert isinstance(model.seen[-1][-1], ToolMessage)


@pytest.mark.parametrize("name", ["get_order", "get_tracking", "list_recent_orders"])
def test_forged_customer_argument_is_ignored(seeded: Any, name: str) -> None:
    _, service = seeded
    tools = {tool.name: tool for tool in build_order_tools(service, "CUST-0001")}
    assert "customer_id" not in tools[name].args
    if name == "list_recent_orders":
        rows = tools[name].invoke({"customer_id": "CUST-0002", "limit": 1000})
        assert rows and all(row["customer_id"] == "CUST-0001" for row in rows)
    else:
        foreign = service.list_recent_orders("CUST-0002")[0]
        from support_agent.orders.models import OrderNotFound

        with pytest.raises(OrderNotFound):
            tools[name].invoke({"order_id": foreign.order_id, "customer_id": "CUST-0002"})


def test_foreign_order_not_found_uses_safe_handoff(seeded: Any) -> None:
    settings, service = seeded
    foreign = service.list_recent_orders("CUST-0002")[0]
    model = ToolFake(
        responses=[
            call(order_id=foreign.order_id, customer_id="CUST-0002"),
            AIMessage(content="invented private facts"),
        ]
    )
    result = ToolsPath(GraphDeps(settings, main_model=model, order_service=service))(state())
    assert result["handoff"].reason == HandoffReason.ORDER_NOT_FOUND
    assert result["tool_errors"] == 1
    assert result["order_context"] is None
    assert "CUST-0002" not in str(result)
    assert "invented" not in result["answer"]


def test_endless_tool_loop_stops_at_exact_model_step_cap(seeded: Any) -> None:
    settings, service = seeded
    model = ToolFake(responses=[call("list_recent_orders")])
    result = ToolsPath(GraphDeps(settings, main_model=model, order_service=service))(state())
    assert len(model.seen) == settings.agent.max_steps
    assert result["agent_steps"] == settings.agent.max_steps
    assert result["handoff"].reason == HandoffReason.AGENT_STEP_CAP
    assert (
        sum(item.startswith("tool_call:") for item in result["trace"]) == settings.agent.max_steps
    )
    assert result["handoff"].order_context["list_recent_orders"]


def test_consecutive_errors_stop_and_do_not_expose_private_exception(
    seeded: Any, monkeypatch: Any, caplog: Any
) -> None:
    settings, service = seeded

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("secret database URL")

    monkeypatch.setattr(service, "list_recent_orders", fail)
    model = ToolFake(responses=[call("list_recent_orders")])
    result = ToolsPath(GraphDeps(settings, main_model=model, order_service=service))(state())
    assert result["tool_errors"] == settings.agent.max_consecutive_tool_errors
    assert len(model.seen) == settings.agent.max_consecutive_tool_errors
    assert result["handoff"].reason == HandoffReason.TOOL_ERROR
    assert "secret" not in str(result) + str(model.seen) + caplog.text


def test_success_resets_error_streak(seeded: Any) -> None:
    settings, service = seeded
    model = ToolFake(
        responses=[
            call("unknown"),
            call("list_recent_orders"),
            call("unknown"),
            call("list_recent_orders"),
            AIMessage(content="Please pick an order."),
        ]
    )
    result = ToolsPath(GraphDeps(settings, main_model=model, order_service=service))(state())
    assert result["tool_errors"] == 2
    assert result["consecutive_tool_errors"] == 0
    assert "handoff" not in result


@pytest.mark.parametrize(
    "responses",
    [
        [AIMessage(content="I invented your order status.")],
        [call("list_recent_orders"), AIMessage(content=" ")],
        [call("unknown"), AIMessage(content="unsupported answer")],
        [call(order_id=123), AIMessage(content="unsupported answer")],
    ],
)
def test_empty_or_unverified_answer_hands_off(seeded: Any, responses: Any) -> None:
    settings, service = seeded
    result = ToolsPath(
        GraphDeps(settings, main_model=ToolFake(responses=responses), order_service=service)
    )(state())
    assert result["handoff"].reason == HandoffReason.TOOL_ERROR
    assert result["answer"].strip()


def test_excess_calls_are_rejected_before_executing(seeded: Any) -> None:
    settings, service = seeded
    message = call("list_recent_orders")
    message.tool_calls *= settings.agent.max_tool_calls_per_step + 1
    result = ToolsPath(
        GraphDeps(settings, main_model=ToolFake(responses=[message]), order_service=service)
    )(state())
    assert result["handoff"].reason == HandoffReason.AGENT_STEP_CAP
    assert result["order_context"] is None


def test_tracking_and_ambiguous_order_use_real_service(seeded: Any) -> None:
    settings, service = seeded
    order_id = service.repository.seed_metadata().edge_cases["delayed_tracking"]
    tracking = service.get_tracking(order_id, "CUST-0001")
    model = ToolFake(
        responses=[call("get_tracking", order_id=order_id), AIMessage(content=tracking.status)]
    )
    result = ToolsPath(GraphDeps(settings, main_model=model, order_service=service))(state())
    assert result["answer"] == tracking.status
    assert result["order_context"]["get_tracking"]["tracking_number"] == tracking.tracking_number
    model = ToolFake(responses=[call("list_recent_orders"), AIMessage(content="Which order?")])
    result = ToolsPath(GraphDeps(settings, main_model=model, order_service=service))(state())
    assert result["answer"] == "Which order?"
    assert result["order_context"]["list_recent_orders"]


def test_human_request_and_missing_identity_do_not_load_any_model() -> None:
    deps = GraphDeps(Settings())
    result = ToolsPath(deps)(state(Intent.TALK_TO_HUMAN))
    assert result["handoff"].reason == HandoffReason.USER_REQUESTED
    assert result["trace"] == ["tools"]
    assert deps.fast_model is None and deps.main_model is None
    missing = state()
    missing.customer_id = None
    assert ToolsPath(deps)(missing)["handoff"].reason == HandoffReason.TOOL_ERROR
    assert deps.main_model is None


@pytest.mark.parametrize(
    "text,category",
    [
        ("hi!", "greeting"),
        ("thanks!", "thanks"),
        ("goodbye", "goodbye"),
        ("what can you do?", "capabilities"),
        ("solve my homework", "fallback"),
        ("this shipment is late", "fallback"),
    ],
)
def test_fixed_templates_have_no_model_dependency(text: str, category: str) -> None:
    from support_agent.graph.handoff import load_templates

    result = fixed_reply(state(Intent.CHITCHAT_OTHER, text))
    assert result["answer"] == load_templates("fixed_replies.yaml")[category]
    assert result["trace"] == ["fixed"]


@pytest.mark.parametrize(
    "ack",
    [
        "I'm sorry this has been frustrating.",
        "",
        "One. Two. Three.",
        "I will refund you tomorrow.",
        "Your compensation is approved.",
    ],
)
def test_complaint_always_acknowledges_and_hands_off(ack: str) -> None:
    model = ToolFake(responses=[AIMessage(content=ack)])
    result = ComplaintPath(GraphDeps(Settings(), fast_model=model))(state(Intent.COMPLAINT))
    assert result["handoff"].reason == HandoffReason.COMPLAINT
    assert result["trace"] == ["complaint"]
    assert "sorry" in result["answer"]
    assert "refund" not in result["answer"]
    assert result["handoff"].conversation[-1].content == result["answer"]


def test_handoff_roundtrip_preserves_snapshot_and_utc_time() -> None:
    original = state(Intent.TALK_TO_HUMAN)
    original.order_context = {"get_order": {"order_id": "ORD-000001"}}
    payload = make_handoff(original, HandoffReason.USER_REQUESTED)["handoff"]
    assert HandoffPayload.model_validate_json(payload.model_dump_json()) == payload
    assert payload.created_at.utcoffset().total_seconds() == 0
    assert payload.conversation[0].content == original.messages[0].content
    assert payload.order_context == original.order_context
