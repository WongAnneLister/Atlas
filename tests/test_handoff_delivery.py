"""A handoff that never reaches the human queue must be logged and flagged, not swallowed."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage

from support_agent.config import get_settings
from support_agent.graph.build import build_graph
from support_agent.graph.deps import GraphDeps
from support_agent.graph.handoff import HandoffReason, make_handoff
from support_agent.graph.nodes.output_guard import OutputGuard
from support_agent.graph.nodes.rewrite import reset_turn
from support_agent.graph.state import ConversationState
from support_agent.handoff.store import HandoffQueueStore


class _BrokenQueue(HandoffQueueStore):
    def enqueue(self, *args: Any, **kwargs: Any) -> Any:
        raise ConnectionError("queue down")

    def add_message(self, *args: Any, **kwargs: Any) -> Any:
        raise ConnectionError("queue down")


def _deps() -> GraphDeps:
    settings = get_settings().model_copy(deep=True)
    settings.handoff.queue_enabled = True
    settings.handoff.human_mode_enabled = True
    settings.graph.checkpoint_backend = "memory"
    queue = _BrokenQueue.from_sqlite_path(":memory:")
    model = FakeListChatModel(responses=["never called"])
    return GraphDeps(settings=settings, fast_model=model, main_model=model, handoff_store=queue)


def test_failed_enqueue_is_logged_and_flagged(caplog: pytest.LogCaptureFixture) -> None:
    deps = _deps()
    state = ConversationState(
        messages=[HumanMessage(content="I want a person.")], customer_id="CUST-1"
    )
    state = state.model_copy(update=make_handoff(state, HandoffReason.USER_REQUESTED))
    with caplog.at_level(logging.ERROR):
        update = OutputGuard(deps)(state)
    assert update["handoff_delivery_failed"] is True
    assert "active_handoff_id" not in update
    assert any("Handoff enqueue failed: ConnectionError" in r.message for r in caplog.records)
    deps.close()


def test_failed_forward_in_human_mode_is_logged_and_flagged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    deps = _deps()
    graph = build_graph(deps)
    config: dict[str, Any] = {"configurable": {"thread_id": "CUST-1:conv-1"}}
    graph.update_state(
        config,
        {
            "customer_id": "CUST-1",
            "human_mode": True,
            "active_handoff_id": "h-1",
            "messages": [AIMessage(content="Transferred to a human.")],
        },
    )
    with caplog.at_level(logging.ERROR):
        result = graph.invoke(
            {"customer_id": "CUST-1", "messages": [HumanMessage(content="Any update?")]},
            config=config,
        )
    state = ConversationState.model_validate(result)
    assert state.trace[-1] == "human_mode"
    assert state.handoff_delivery_failed is True
    assert any("not added to handoff h-1" in r.message for r in caplog.records)

    # The flag is per turn: a later turn that succeeds must not inherit it.
    assert reset_turn()["handoff_delivery_failed"] is False
    deps.close()
