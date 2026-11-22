"""Checkpoint factories and eval thread namespaces."""

from datetime import date
from pathlib import Path

import pytest

from support_agent.config import get_settings
from support_agent.graph.deps import GraphDeps


def test_eval_runs_never_share_threads() -> None:
    from eval.thread_ids import EvalThreads

    first, second = EvalThreads("smoke"), EvalThreads("smoke")
    assert first("test", "item-1") != second("test", "item-1")
    assert first("test", "item-1") == first("test", "item-1")
    assert first("test", "item-1") != first("test", "item-2")


def test_checkpoint_switch(tmp_path: Path) -> None:
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.checkpoint.sqlite import SqliteSaver

    settings = get_settings()
    with GraphDeps(settings) as deps:
        assert isinstance(deps.checkpointer(), InMemorySaver)
    settings.graph.checkpoint_backend = "sqlite"
    settings.graph.checkpoint_path = str(tmp_path / "checkpoints.sqlite")
    with GraphDeps(settings) as deps:
        assert isinstance(deps.checkpointer(), SqliteSaver)
    settings.graph.checkpoint_backend = "postgres"
    settings.database_url = None
    with GraphDeps(settings) as deps, pytest.raises(ValueError, match="requires DATABASE_URL"):
        deps.checkpointer()


def test_checkpoint_serializer_keeps_typed_order(seeded) -> None:
    from support_agent.graph.postgres import checkpoint_serializer
    from support_agent.orders.models import Order

    _, service = seeded
    order = service.get_order("ORD-000001", "CUST-0001")
    serde = checkpoint_serializer()
    value = serde.loads_typed(serde.dumps_typed(order))
    assert isinstance(value, Order)
    assert value == order


def test_checkpoint_serializer_keeps_retrieval_filters() -> None:
    from support_agent.graph.postgres import checkpoint_serializer
    from support_agent.retrieval.filters import RetrievalFilters

    filters = RetrievalFilters(as_of=date(2026, 9, 1), product_category="hair_dryers")
    serde = checkpoint_serializer()
    assert serde.loads_typed(serde.dumps_typed(filters)) == filters


def test_checkpoint_serializers_keep_part_routing_and_evidence(tmp_path: Path) -> None:
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.graph import END, START, StateGraph

    from support_agent.graph.intents import Intent
    from support_agent.graph.parts import PartRetrievalResult, QueryPart
    from support_agent.graph.postgres import checkpoint_serializer
    from support_agent.graph.state import ConversationState
    from support_agent.retrieval.filters import RetrievalFilters

    filters = RetrievalFilters(as_of=date(2026, 11, 9))
    part = QueryPart(
        text="What is the returns policy?",
        key_terms=["returns"],
        intent=Intent.POLICY_QUESTION,
        filters=filters,
        source_numbers=[1],
    )
    retrieval = PartRetrievalResult(index=0, filters=filters)
    serde = checkpoint_serializer()
    assert serde.loads_typed(serde.dumps_typed(part)) == part
    assert serde.loads_typed(serde.dumps_typed(retrieval)) == retrieval

    state = StateGraph(ConversationState)
    state.add_node("keep", lambda _: {"route_source": "parts"})
    state.add_edge(START, "keep")
    state.add_edge("keep", END)
    config = {"configurable": {"thread_id": "multipart-checkpoint"}}
    with SqliteSaver.from_conn_string(str(tmp_path / "parts.sqlite")) as saver:
        graph = state.compile(checkpointer=saver)
        graph.invoke({"parts": [part], "part_retrievals": [retrieval]}, config)
        restored = graph.get_state(config).values
    assert restored["route_source"] == "parts"
    assert restored["parts"] == [part]
    assert restored["part_retrievals"] == [retrieval]
