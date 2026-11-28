"""Refund scenarios in the simulator: clean order state per chat and the refusal rule."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from eval.sim.metrics import evaluate_transcript
from eval.sim.models import ConversationTranscript, SimTurn, SuccessChecks
from eval.sim.order_state import (
    drop_refund_requests,
    refund_request_ids,
    require_no_refund_requests,
)
from eval.sim.run import run_suite

from support_agent.config import Settings, get_settings
from support_agent.orders.seed import seed_orders
from support_agent.orders.service import OrderService
from test_sim import _sample_scenario

REFUSAL = ["input_guard", "rewrite", "classify", "after_sales", "refund_decide", "refund_act"]


def _seeded(tmp_path: Path) -> tuple[Settings, OrderService]:
    settings: Settings = get_settings().model_copy(deep=True)
    settings.orders.db_path = str(tmp_path / "orders.sqlite")
    seed_orders(settings)
    return settings, OrderService(platform=settings)


def _refund_request(service: OrderService) -> str:
    order = service.get_order("ORD-000001", "CUST-0001")
    request = service.create_refund_request(
        order.order_id, order.customer_id, [order.items[0].item_id], "Earlier run"
    )
    return request.request_id


def test_a_suite_refuses_an_orders_db_that_already_holds_refund_requests(tmp_path: Path) -> None:
    # 27c: a refund request left in the dev database made every eligible-refund chat hand off.
    settings, service = _seeded(tmp_path)
    try:
        require_no_refund_requests(service)
        request_id = _refund_request(service)
        with pytest.raises(ValueError, match="already holds 1 refund request"):
            asyncio.run(
                run_suite(
                    settings,
                    [_sample_scenario()],
                    simulator=None,  # type: ignore[arg-type]
                    graph_deps=None,  # type: ignore[arg-type]
                    order_service=service,
                )
            )
        assert drop_refund_requests(service, {request_id}) == 1
        assert refund_request_ids(service) == set()
        assert service.pending_refund_item_ids("ORD-000001", "CUST-0001") == []
    finally:
        service.close()


def _refund_chat(*turns: tuple[list[str], str | None]) -> ConversationTranscript:
    return ConversationTranscript(
        scenario_id="sim-022-refund_ineligible",
        category="refund_ineligible",
        customer_id="CUST-0001",
        turns=[
            SimTurn(
                turn_index=index,
                user_message="refund please",
                agent_message="I cannot approve this request. You can ask a human agent.",
                route=route,
                handoff_reason=handoff,
                citations=[{"n": 1}],
            )
            for index, (route, handoff) in enumerate(turns, start=1)
        ],
    )


def test_a_refusal_followed_by_a_requested_human_still_counts_as_refused() -> None:
    scenario = _sample_scenario(
        id="sim-022-refund_ineligible",
        category="refund_ineligible",
        expected_outcome="refund_denied",
        checkpoints=[],
        success_checks=SuccessChecks(require_citations=True),
    )
    asked_human = _refund_chat((REFUSAL, None), (["input_guard", "tools"], "user_requested"))
    assert evaluate_transcript(scenario, asked_human).task_success
    assert evaluate_transcript(scenario, _refund_chat((REFUSAL, None))).task_success
    # After the refusal a handoff for any reason keeps it (author, 2026-11-28); sim-024
    # asked for an exception that no policy covers and was handed off with low_evidence.
    exception = _refund_chat((REFUSAL, None), (["input_guard", "retrieve"], "low_evidence"))
    assert evaluate_transcript(scenario, exception).task_success
    policy_handoff = _refund_chat((REFUSAL, None), (REFUSAL, "policy_requires_human"))
    assert evaluate_transcript(scenario, policy_handoff).task_success
    # A handoff before the refusal, or no refusal at all, is still a failure.
    early = _refund_chat((["input_guard", "tools"], "user_requested"), (REFUSAL, None))
    assert not evaluate_transcript(scenario, early).task_success
    no_refusal = _refund_chat((["input_guard", "tools"], "user_requested"))
    assert not evaluate_transcript(scenario, no_refusal).task_success


def test_a_scenario_customer_outside_the_demo_list_still_gets_a_session(tmp_path: Path) -> None:
    # 12c: sim-017, sim-018 and sim-023 use CUST-TS01, which is not among the first
    # api.demo_customer_limit customers, so /api/session answered 403 for all of them.
    from eval.sim.user import UserSimulator
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    from support_agent.graph.deps import GraphDeps
    from test_sim import _StaticRetriever

    settings, service = _seeded(tmp_path)
    settings.planning.enabled = False
    settings.cache.enabled = False
    assert settings.api.demo_customer_limit < 50
    graph_deps = GraphDeps(
        settings=settings,
        fast_model=FakeListChatModel(responses=["x"]),
        main_model=FakeListChatModel(responses=["x"]),
        retriever=_StaticRetriever([]),
        order_service=service,
        allow_untuned_gate=True,
    )
    scenario = _sample_scenario(id="s-ts01", customer_id="CUST-TS01", checkpoints=[])
    simulator = UserSimulator(FakeListChatModel(responses=["[DONE]"]), model_name="fake")
    try:
        [transcript] = asyncio.run(
            run_suite(
                settings,
                [scenario],
                simulator=simulator,
                graph_deps=graph_deps,
                order_service=service,
            )
        )
    finally:
        service.close()
    assert transcript.stop_reason == "done"
