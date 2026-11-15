"""Graph state resets, provider failures, and CLI checks without network access."""

from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import ValidationError

from chat_cli import main
from support_agent.config import Settings
from support_agent.graph.build import build_graph
from support_agent.graph.deps import GraphDeps
from support_agent.graph.handoff import HandoffReason
from support_agent.graph.intents import Intent
from support_agent.graph.nodes.complaint import ComplaintPath
from support_agent.graph.nodes.tools_path import ToolsPath
from support_agent.llm import override_chat_model
from test_graph import fake
from test_tool_paths import ToolFake, call, state


@pytest.fixture(autouse=True)
def _free_text_mode(seeded: Any) -> None:
    """These tests cover the free-text order reply mode (template mode: test_order_replies)."""
    seeded[0].agent.order_replies = "free_text"


def test_provider_failure_hands_off_without_private_body(
    seeded: Any, monkeypatch: Any, caplog: Any
) -> None:
    settings, service = seeded

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("secret provider body")

    monkeypatch.setattr(ToolFake, "invoke", fail)
    model = ToolFake(responses=[AIMessage(content="unused")])
    deps = GraphDeps(settings, fast_model=model, main_model=model, order_service=service)
    result = ToolsPath(deps)(state())
    assert result["handoff"].reason == HandoffReason.TOOL_ERROR
    assert "secret" not in str(result) + caplog.text
    result = ComplaintPath(deps)(state(Intent.COMPLAINT))
    assert result["handoff"].reason == HandoffReason.COMPLAINT
    assert "sorry" in result["answer"]
    assert "secret" not in str(result) + caplog.text


def test_no_shipment_is_successful_null_data(seeded: Any) -> None:
    settings, service = seeded
    order_id = service.repository.seed_metadata().edge_cases["pending"]
    model = ToolFake(
        responses=[
            call("get_tracking", order_id=order_id),
            AIMessage(content="Tracking is unavailable for this order."),
        ]
    )
    result = ToolsPath(GraphDeps(settings, main_model=model, order_service=service))(state())
    assert result["order_context"]["get_tracking"] is None
    assert result["tool_errors"] == 0
    assert "handoff" not in result


def test_clarification_uses_fresh_tools_and_clears_stale_handoff(seeded: Any) -> None:
    settings, service = seeded
    order = service.list_recent_orders("CUST-0001")[0]
    model = ToolFake(
        responses=[
            call("list_recent_orders"),
            AIMessage(content="Which order?"),
            call(order_id=order.order_id),
            AIMessage(content=order.status),
        ]
    )
    fast = fake(
        Intent.ORDER_STATUS,
        Intent.ORDER_STATUS,
        Intent.CHITCHAT_OTHER,
        rewrite=f"Where is {order.order_id}?",
    )
    with GraphDeps(settings, fast_model=fast, main_model=model, order_service=service) as deps:
        graph = build_graph(deps)
        config = {"configurable": {"thread_id": "CUST-0001:clarify"}}
        graph.invoke(
            {"messages": [HumanMessage(content="Where is my order?")], "customer_id": "CUST-0001"},
            config,
        )
        result = graph.invoke({"messages": [HumanMessage(content=order.order_id)]}, config)
        assert result["answer"] == order.status
        assert result["agent_steps"] == 2
        assert "list_recent_orders" not in result["order_context"]
        result = graph.invoke({"messages": [HumanMessage(content="thanks!")]}, config)
    assert result["answer"].startswith("You're welcome")
    assert result["agent_steps"] == result["tool_errors"] == 0
    assert result["order_context"] is None and result["handoff"] is None
    assert result["trace"][-3:] == ["rewrite", "classify", "fixed"]


def test_cli_one_shot_uses_graph_and_real_seeded_database(
    seeded: Any, monkeypatch: Any, capsys: Any
) -> None:
    settings, service = seeded
    order = service.list_recent_orders("CUST-0001")[0]
    model = ToolFake(responses=[call(order_id=order.order_id), AIMessage(content=order.status)])
    monkeypatch.setattr("chat_cli.get_settings", lambda: settings)
    monkeypatch.setattr("chat_cli.load_dotenv", lambda: False)
    with override_chat_model("fast", fake(Intent.ORDER_STATUS)), override_chat_model("main", model):
        assert main(["--customer", "CUST-0001", "--question", f"Where is {order.order_id}?"]) == 0
    output = capsys.readouterr().out
    assert f"Agent: {order.status}" in output
    assert "rewrite -> classify -> tools -> tool_call:get_order:" in output


@pytest.mark.parametrize(
    "field",
    [
        "max_steps",
        "max_consecutive_tool_errors",
        "max_tool_calls_per_step",
        "trace_max_chars",
        "complaint_max_sentences",
    ],
)
def test_agent_limits_must_be_positive(field: str) -> None:
    data = Settings().model_dump()
    data["agent"][field] = 0
    with pytest.raises(ValidationError):
        Settings(**data)
