"""Order-tool answers may only state facts found in this turn's tool results."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage

from support_agent.graph.deps import GraphDeps
from support_agent.graph.handoff import HandoffReason
from support_agent.graph.nodes.tools_path import ToolsPath
from support_agent.graph.order_grounding import (
    OrderGrounding,
    SentenceCheck,
    answer_sentences,
    tool_data_text,
    ungrounded_sentences,
)
from test_tool_paths import ToolFake, call, state


@pytest.fixture(autouse=True)
def _free_text_mode(seeded: Any) -> None:
    """These tests cover the free-text order reply mode (template mode: test_order_replies)."""
    seeded[0].agent.order_replies = "free_text"
    seeded[0].agent.order_grounding = True


def fact(index: int, *quotes: str) -> SentenceCheck:
    return SentenceCheck(index=index, kind="fact", quotes=list(quotes))


def test_answer_is_split_into_lines_and_sentences() -> None:
    answer = "Your order shipped. It arrives Nov 12!\n\n- **ORD-1**: shipped\n2. Need more?"
    assert answer_sentences(answer) == [
        "Your order shipped.",
        "It arrives Nov 12!",
        "**ORD-1**: shipped",
        "Need more?",
    ]


def test_every_quote_must_match_and_no_sentence_may_be_skipped() -> None:
    data = tool_data_text(
        {"get_tracking": {"carrier": "Mock Carrier", "status": "shipped", "order_id": "ORD-7"}}
    )
    sentences = ["It shipped.", "Carrier and id.", "A friend may collect it.", "Joined.", "Ok?"]
    decision = OrderGrounding(
        sentences=[
            fact(1, '"status": "shipped"'),
            fact(2, '"carrier": "Mock Carrier"', '"order_id": "ORD-7"'),
            fact(3),
            fact(4, '"carrier": "Mock Carrier" ... "status": "shipped"'),
            SentenceCheck(index=5, kind="other", quotes=[]),
        ]
    )
    assert ungrounded_sentences(decision, sentences, data) == ["A friend may collect it."]
    skipped = OrderGrounding(sentences=[fact(1, '"status": "shipped"')])
    assert ungrounded_sentences(skipped, ["It shipped.", "Free returns."], data) == [
        "Free returns."
    ]
    joined = OrderGrounding(sentences=[fact(1, '"carrier": "Mock Carrier", "status": "x"')])
    assert ungrounded_sentences(joined, ["It shipped."], data) == ["It shipped."]


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
    grounding = {"sentences": [{"index": 1, "kind": "fact", "quotes": []}]}
    result, model = _run(seeded, grounding, answer)
    assert result["fallback_to_knowledge"] is True
    assert "answer" not in result
    assert result["trace"][-2:] == ["ungrounded:1", "tools_fallback"]
    assert answer in str(model.grounding_seen[0][-1].content)


def test_order_fact_quoted_from_tool_data_is_released(seeded: Any) -> None:
    _, service = seeded
    order = service.list_recent_orders("CUST-0001")[0]
    grounding = {
        "sentences": [{"index": 1, "kind": "fact", "quotes": [f'"status": "{order.status}"']}]
    }
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
    grounding = {"sentences": [{"index": 1, "kind": "fact", "quotes": []}]}
    result, _ = _run(seeded, grounding, "Store rule.")
    assert result["handoff"].reason == HandoffReason.INVALID_ANSWER
    assert "Store rule." not in result["answer"]


def test_grounding_off_keeps_the_old_release(seeded: Any) -> None:
    settings, _ = seeded
    settings.agent.order_grounding = False
    grounding = {"sentences": [{"index": 1, "kind": "fact", "quotes": []}]}
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
        grounding={
            "sentences": [
                {"index": 1, "kind": "fact", "quotes": []},
                {"index": 2, "kind": "fact", "quotes": []},
            ]
        },
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
    assert trace[:4] == ["input_guard", "rewrite", "classify", "tools"]
    assert trace[4].startswith("tool_call:list_recent_orders")
    assert trace[-6:] == [
        "ungrounded:1",
        "tools_fallback",
        "retrieve",
        "gate",
        "handoff",
        "output_guard",
    ]
    assert result["handoff"].reason == HandoffReason.LOW_EVIDENCE
    assert "friend" not in result["answer"]


def test_a_reply_without_a_structured_call_is_retried(seeded: Any) -> None:
    settings, service = seeded
    settings.agent.grounding_attempts = 2
    order = service.list_recent_orders("CUST-0001")[0]
    grounded = {
        "sentences": [{"index": 1, "kind": "fact", "quotes": [f'"status": "{order.status}"']}]
    }
    result, model = _run(seeded, [None, grounded])
    assert result["answer"] == order.status
    assert len(model.grounding_seen) == 2
    assert "grounding_retry:1" in result["trace"]
    assert "grounding_error" not in result["trace"]


def test_retries_are_bounded_and_then_fail_closed(seeded: Any) -> None:
    settings, _ = seeded
    settings.agent.grounding_attempts = 2
    result, model = _run(seeded, [None, None, {"sentences": []}])
    assert len(model.grounding_seen) == 2
    assert result["fallback_to_knowledge"] is True
    assert result["trace"][-3:] == ["grounding_retry:1", "grounding_error", "tools_fallback"]


def test_graph_repairs_once_even_if_standalone_limit_is_one(seeded: Any) -> None:
    settings, _ = seeded
    settings.agent.grounding_attempts = 1
    result, model = _run(seeded, [None, {"sentences": []}])
    assert len(model.grounding_seen) == 2
    assert "grounding_retry:1" in result["trace"]
    assert "grounding_error" not in result["trace"]


def test_a_raised_error_is_not_retried(seeded: Any) -> None:
    settings, _ = seeded
    settings.agent.grounding_attempts = 3
    result, model = _run(seeded, [RuntimeError("relay down"), {"sentences": []}])
    assert len(model.grounding_seen) == 1
    assert result["trace"][-2:] == ["grounding_error", "tools_fallback"]
