"""Checkpoint factories and eval thread namespaces."""

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
