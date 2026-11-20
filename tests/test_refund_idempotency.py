"""Persistent refund replay keys and checkpoint-compatible handoff keys."""

from datetime import UTC, datetime
from json import dumps
from uuid import NAMESPACE_URL, uuid5

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableLambda

from support_agent.graph.handoff import HandoffPayload, HandoffReason, make_handoff
from support_agent.graph.postgres import checkpoint_serializer
from support_agent.graph.state import ConversationState
from test_refund_flow import DecisionFake, deps, yes_decision


def legacy_request_id(customer_id: str, order_id: str, turn_id: str) -> str:
    key = uuid5(NAMESPACE_URL, dumps(["atlas-refund", customer_id, order_id, turn_id]))
    return f"REF-{key.hex}"


def test_graph_replay_upgrades_a_legacy_sqlite_row_without_replacing_it(seeded) -> None:
    from support_agent.graph.build import build_graph

    settings, service = seeded
    order = service.get_order("ORD-000001", "CUST-0001")
    decision = yes_decision(order)
    turn_id = "before-upgrade"
    request_id = legacy_request_id(order.customer_id, order.order_id, turn_id)
    reason = decision["reasons"][0]
    with service.repository.connection(write=True) as connection:
        connection.exec_driver_sql("DROP TABLE refund_request_items")
        connection.exec_driver_sql("DROP TABLE refund_requests")
        connection.exec_driver_sql(
            "CREATE TABLE refund_requests ("
            "request_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, customer_id TEXT NOT NULL, "
            "reason TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, "
            "UNIQUE (request_id, order_id), FOREIGN KEY (order_id, customer_id) "
            "REFERENCES orders (order_id, customer_id))"
        )
        connection.exec_driver_sql(
            "CREATE TABLE refund_request_items ("
            "request_id TEXT NOT NULL, order_id TEXT NOT NULL, item_id TEXT NOT NULL, "
            "PRIMARY KEY (request_id, item_id), FOREIGN KEY (request_id, order_id) "
            "REFERENCES refund_requests (request_id, order_id))"
        )
        connection.exec_driver_sql(
            "INSERT INTO refund_requests VALUES (?, ?, ?, ?, ?, ?)",
            (
                request_id,
                order.order_id,
                order.customer_id,
                reason,
                "pending_review",
                datetime(2026, 11, 20, tzinfo=UTC).isoformat(),
            ),
        )
        connection.exec_driver_sql(
            "INSERT INTO refund_request_items VALUES (?, ?, ?)",
            (request_id, order.order_id, order.items[0].item_id),
        )

    with deps(
        settings, service, DecisionFake(responses=["unused"], decisions=[decision])
    ) as graph_deps:
        result = build_graph(graph_deps).invoke(
            {
                "messages": [HumanMessage(content="Refund ORD-000001", id=turn_id)],
                "customer_id": order.customer_id,
            },
            {"configurable": {"thread_id": "legacy"}},
        )
    assert result["trace"][-2:] == ["refund_decide", "refund_act"]
    assert result["refund_request"]["request_id"] == request_id
    with service.repository.connection() as connection:
        key = connection.exec_driver_sql("SELECT idempotency_key FROM refund_requests").scalar_one()
        assert key
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []


def test_same_turn_id_in_two_conversations_keeps_refund_requests_separate(seeded) -> None:
    from support_agent.graph.build import build_graph

    settings, service = seeded
    order = service.get_order("ORD-000001", "CUST-0001")
    ids: list[str] = []
    for thread_id in ("shop-one", "shop-two"):
        decision = yes_decision(order)
        with deps(
            settings, service, DecisionFake(responses=["unused"], decisions=[decision])
        ) as graph_deps:
            result = build_graph(graph_deps).invoke(
                {
                    "messages": [HumanMessage(content="Refund ORD-000001", id="same-turn-id")],
                    "customer_id": order.customer_id,
                },
                {"configurable": {"thread_id": thread_id}},
            )
        assert result["trace"][-2:] == ["refund_decide", "refund_act"]
        ids.append(result["refund_request"]["request_id"])
    assert ids[0] != ids[1]
    with service.repository.connection() as connection:
        assert (
            connection.exec_driver_sql(
                "SELECT COUNT(DISTINCT idempotency_key) FROM refund_requests"
            ).scalar_one()
            == 2
        )


def test_handoff_key_is_stable_by_thread_and_turn_and_restores_from_checkpoint() -> None:
    def handoff(state: ConversationState) -> HandoffPayload:
        return make_handoff(state, HandoffReason.USER_REQUESTED)["handoff"]

    node = RunnableLambda(handoff)

    def run(thread_id: str, turn_id: str) -> HandoffPayload:
        state = ConversationState(messages=[HumanMessage(content="Help", id=turn_id)])
        return node.invoke(state, config={"configurable": {"thread_id": thread_id}})

    first = run("thread-one", "turn-one")
    traced = node.invoke(
        ConversationState(messages=[HumanMessage(content="Help", id="turn-one")]),
        config={"configurable": {"thread_id": "thread-one"}, "metadata": {"trace_id": "trace-one"}},
    )
    assert traced.trace_id == "trace-one"
    assert traced.idempotency_key == first.idempotency_key
    assert first.trace_id is None
    assert first.idempotency_key
    assert first.idempotency_key == run("thread-one", "turn-one").idempotency_key
    assert first.idempotency_key != run("thread-two", "turn-one").idempotency_key
    assert first.idempotency_key != run("thread-one", "turn-two").idempotency_key
    serializer = checkpoint_serializer()
    assert serializer.loads_typed(serializer.dumps_typed(traced)) == traced
    old_fields = traced.model_dump(exclude={"idempotency_key", "trace_id"})
    restored = HandoffPayload.model_validate(old_fields)
    assert restored.idempotency_key is restored.trace_id is None


def test_refund_action_without_graph_identity_does_not_write(seeded) -> None:
    from support_agent.graph.nodes.refund import RefundPath

    settings, service = seeded
    order = service.get_order("ORD-000001", "CUST-0001")
    state = ConversationState(
        customer_id=order.customer_id,
        refund_order_id=order.order_id,
        refund_decision=yes_decision(order),
    )
    with deps(settings, service, DecisionFake(responses=["unused"])) as graph_deps:
        result = RefundPath(graph_deps).act(state)
    assert result["trace"] == ["handoff"]
    assert result["handoff"].reason == HandoffReason.POLICY_REQUIRES_HUMAN
    with service.repository.connection() as connection:
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM refund_requests").scalar_one() == 0


def test_decision_timeout_keeps_one_dependency_handoff(seeded) -> None:
    from langchain_core.messages import AIMessage

    from support_agent.graph.build import build_graph
    from test_refund_flow import invoke

    settings, service = seeded
    settings.reliability.retry.max_attempts = 1
    main = DecisionFake(responses=["unused"], decisions=[TimeoutError("decision deadline")])
    with deps(settings, service, main) as graph_deps:
        result = invoke(build_graph(graph_deps), "Refund ORD-000001")
    assert result["trace"] == [
        "rewrite",
        "classify",
        "after_sales",
        "refund_identify",
        "refund_load",
        "refund_retrieve",
        "handoff",
    ]
    assert result["handoff"].reason == HandoffReason.DEPENDENCY_UNAVAILABLE
    assert sum(isinstance(message, AIMessage) for message in result["messages"]) == 1
    assert main.decision_calls == 1
    with service.repository.connection() as connection:
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM refund_requests").scalar_one() == 0


@pytest.mark.parametrize("key", [None, "refund-turn"])
def test_guarded_refund_insert_after_deadline_rolls_back(seeded, monkeypatch, key) -> None:
    from sqlalchemy import event

    from support_agent.graph.deps import GraphDeps
    from support_agent.orders import sql_repository
    from support_agent.reliability import stores

    settings, service = seeded
    settings.reliability.retry.max_attempts = 1
    order = service.get_order("ORD-000001", "CUST-0001")
    now = 10.0
    monkeypatch.setattr(stores, "monotonic", lambda: now, raising=False)
    monkeypatch.setattr(sql_repository, "monotonic", lambda: now, raising=False)

    def expire_after_insert(connection, cursor, statement, parameters, context, executemany):
        nonlocal now
        if statement.startswith("INSERT INTO refund_request_items"):
            now += settings.reliability.timeouts_s.orders_db + 1

    event.listen(service.repository.engine, "after_cursor_execute", expire_after_insert)
    with (
        GraphDeps(settings, order_service=service) as graph_deps,
        pytest.raises(TimeoutError, match="Refund transaction deadline"),
    ):
        graph_deps.guarded_orders().create_refund_request(
            order.order_id,
            order.customer_id,
            [order.items[0].item_id],
            "Issue",
            idempotency_key=key,
        )
    with service.repository.connection() as connection:
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM refund_requests").scalar_one() == 0
        assert (
            connection.exec_driver_sql("SELECT COUNT(*) FROM refund_request_items").scalar_one()
            == 0
        )
