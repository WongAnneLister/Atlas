"""Offline tests for the multi-turn user simulator, scenario suite, metrics, and ASGI runner."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from eval.sim.build_scenarios import build_scenarios, load_scenarios, write_scenarios
from eval.sim.metrics import aggregate_evaluations, evaluate_transcript
from eval.sim.models import (
    ConversationTranscript,
    FactCheckpoint,
    Persona,
    Scenario,
    SimTurn,
    SuccessChecks,
    ToolCallRecord,
)
from eval.sim.report import render_sim_report, render_validity_template
from eval.sim.run import run_suite
from eval.sim.user import UserSimulator
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.runnables import RunnableLambda

from support_agent.config import Settings, get_settings
from support_agent.graph.deps import GraphDeps
from support_agent.orders.seed import seed_orders
from support_agent.orders.service import OrderService
from support_agent.retrieval.types import RetrievedChunk


class _StructuredFake(FakeListChatModel):
    payloads: list[dict[str, Any]]
    calls: int = 0

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        def invoke(_: Any) -> dict[str, Any]:
            self.calls += 1
            idx = min(self.calls - 1, len(self.payloads) - 1)
            return {
                "parsed": schema.model_validate(self.payloads[idx]),
                "raw": None,
                "parsing_error": None,
            }

        return RunnableLambda(invoke)


class _StaticRetriever:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self.chunks = chunks

    def supports_filters(self) -> bool:
        return True

    def retrieve(self, query: str, top_k: int, filters: Any = None) -> list[RetrievedChunk]:
        return list(self.chunks[:top_k])


def _chunk(text: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="c-ret-1",
        doc_id="returns",
        title="Returns",
        section_id="returns.maktek_faqs.window",
        heading_path="Returns > Return Window",
        text=text,
        n_tokens=len(text.split()),
        scores={"rerank": 0.94, "rerank_logit": 2.8},
        ranks={"rerank": 1},
    )


def _sample_scenario(**overrides: Any) -> Scenario:
    base: dict[str, Any] = {
        "id": "sim-test-1",
        "split": "test",
        "category": "topic_switch",
        "customer_id": "CUST-0001",
        "persona": Persona(tone="polite", verbosity="normal", patience=8),
        "goal": "Check ORD-000009, switch topic, then confirm ORD-000009.",
        "facts": {"order_id": "ORD-000009"},
        "expected_outcome": "answer",
        "expected_tool_calls": ["get_order", "get_tracking"],
        "checkpoints": [
            FactCheckpoint(turn_hint=3, fact_key="order_id", expected_substrings=["ORD-000009"])
        ],
        "max_turns": 6,
        "success_checks": SuccessChecks(required_substrings=["ORD-000009"]),
    }
    base.update(overrides)
    return Scenario(**base)


def test_scenario_suite_counts_categories_and_determinism(tmp_path: Path) -> None:
    scenarios = build_scenarios()
    assert len(scenarios) == 60
    assert sum(s.split == "dev" for s in scenarios) == 30
    assert sum(s.split == "test" for s in scenarios) == 30
    assert sum(s.nightly for s in scenarios) == 10
    assert all(s.split == "test" for s in scenarios if s.nightly)
    assert len({s.id for s in scenarios}) == 60
    assert len({s.category for s in scenarios}) == 12

    out1 = tmp_path / "a.jsonl"
    out2 = tmp_path / "b.jsonl"
    write_scenarios(scenarios, out1, tmp_path / "a.csv")
    write_scenarios(build_scenarios(), out2, tmp_path / "b.csv")
    assert out1.read_bytes() == out2.read_bytes()
    assert len(load_scenarios(out1)) == 60


def test_trajectory_metrics_on_handwritten_transcripts() -> None:
    scenario = _sample_scenario()
    good = ConversationTranscript(
        scenario_id=scenario.id,
        category=scenario.category,
        customer_id="CUST-0001",
        repeat_index=0,
        turns=[
            SimTurn(
                turn_index=1,
                user_message="Please check ORD-000009.",
                agent_message="Order ORD-000009 is in transit.",
                tool_calls=[
                    ToolCallRecord(name="get_order", args={"order_id": "ORD-000009"}),
                    ToolCallRecord(name="get_tracking", args={"order_id": "ORD-000009"}),
                ],
                input_tokens=400,
                output_tokens=80,
            ),
            SimTurn(
                turn_index=2,
                user_message="What is the return window?",
                agent_message="Returns are accepted within 30 days [1].",
                citations=[{"n": 1, "chunk_id": "c1", "section_id": "s1", "heading_path": "R"}],
                input_tokens=800,
                output_tokens=60,
            ),
            SimTurn(
                turn_index=3,
                user_message="Remind me of my order ID?",
                agent_message="Your order is ORD-000009.",
                input_tokens=1200,
                output_tokens=40,
            ),
        ],
    )
    ev_good = evaluate_transcript(scenario, good)
    assert ev_good.task_success is True
    assert ev_good.tool_call_precision == 1.0
    assert ev_good.tool_call_recall == 1.0
    assert ev_good.wrong_customer_access is False
    assert ev_good.turns_to_success == 3
    assert ev_good.redundant_questions == 0
    assert ev_good.fact_retention == 1.0
    assert ev_good.loop_detected is False
    assert ev_good.handoff_appropriate is True
    assert ev_good.tokens_by_turn == [400, 800, 1200]

    # Bad transcript: redundant question, tool loop (>=3 identical calls), wrong customer access,
    # and forgot the order ID at turn 3.
    bad = ConversationTranscript(
        scenario_id=scenario.id,
        category=scenario.category,
        customer_id="CUST-0001",
        repeat_index=1,
        turns=[
            SimTurn(
                turn_index=1,
                user_message="Please check ORD-000009.",
                agent_message="Checking now.",
                tool_calls=[
                    ToolCallRecord(
                        name="get_order",
                        args={"order_id": "ORD-000009"},
                        customer_id_accessed="CUST-0002",
                    ),
                    ToolCallRecord(name="get_order", args={"order_id": "ORD-000009"}),
                    ToolCallRecord(name="get_order", args={"order_id": "ORD-000009"}),
                ],
                input_tokens=500,
            ),
            SimTurn(
                turn_index=2,
                user_message="Any update?",
                agent_message="Could you please provide your order number?",
                input_tokens=900,
            ),
            SimTurn(
                turn_index=3,
                user_message="Remind me of my order ID?",
                agent_message="I do not have an order ID on file.",
                input_tokens=1300,
            ),
        ],
    )
    ev_bad = evaluate_transcript(scenario, bad)
    assert ev_bad.task_success is False
    assert ev_bad.wrong_customer_access is True
    assert ev_bad.redundant_questions == 1
    assert ev_bad.fact_retention == 0.0
    assert ev_bad.loop_detected is True
    assert ev_bad.turns_to_success is None

    agg = aggregate_evaluations([ev_good, ev_bad], n_resamples=200, seed=27)
    assert agg["n_runs"] == 2
    assert agg["wrong_customer_access"]["count"] == 1
    assert agg["repeat_task_success_mean_std"] == 0.5
    assert [p["turn"] for p in agg["tokens_per_turn_curve"]] == [1, 2, 3]


def test_user_simulator_isolation_and_choose_order() -> None:
    seen_prompts: list[list[Any]] = []

    class RecordingFake(FakeListChatModel):
        def invoke(self, input: Any, *args: Any, **kwargs: Any) -> Any:
            seen_prompts.append(list(input))
            return super().invoke(input, *args, **kwargs)

    model = RecordingFake(responses=["What is the return window?", "Thanks! [DONE]"])
    sim = UserSimulator(model, model_name="fake-sim")
    scenario = _sample_scenario(facts={"order_id": "ORD-000002"})

    r1 = sim.next_turn(scenario, [], 1)
    assert r1.text == "What is the return window?" and r1.done is False

    r2 = sim.next_turn(
        scenario,
        [("user", r1.text), ("assistant", "Returns are accepted within 30 days.")],
        2,
    )
    assert r2.text == "Thanks!" and r2.done is True
    assert len(seen_prompts) == 2

    choice = sim.choose_order(
        scenario,
        [{"order_id": "ORD-000001"}, {"order_id": "ORD-000002"}],
    )
    assert choice == "ORD-000002"


def test_asgi_runner_completes_handles_interrupt_and_stops_at_max_turns(
    tmp_path: Path,
) -> None:
    settings: Settings = get_settings().model_copy(deep=True)
    settings.orders.db_path = str(tmp_path / "orders.sqlite")
    settings.planning.enabled = False
    settings.grounding.enabled = False
    settings.cache.enabled = False
    settings.api.rate_limit.per_customer = 1000
    settings.api.rate_limit.per_ip = 1000
    seed_orders(settings)

    order_service = OrderService(platform=settings)
    recent_order_id = order_service.list_recent_orders("CUST-0001")[0].order_id
    chunks = [_chunk("Generic store returns are accepted within 30 days of delivery.")]
    retriever = _StaticRetriever(chunks)

    # Scenario 1: policy Q&A completes on [DONE] at turn 1.
    # Scenario 2: refund without order ID triggers picker interrupt and resumes ORD-000001.
    # Scenario 3: simulator never sends [DONE] -> stops cleanly at max_turns=2.
    s_policy = _sample_scenario(
        id="s-policy",
        category="policy_qa",
        expected_outcome="answer",
        expected_tool_calls=[],
        checkpoints=[],
        max_turns=3,
        success_checks=SuccessChecks(required_substrings=["30"], require_citations=True),
    )
    s_interrupt = _sample_scenario(
        id="s-interrupt",
        category="order_picker_interrupt",
        facts={"order_id": recent_order_id},
        expected_outcome="handoff:policy_requires_human",
        expected_tool_calls=[],
        checkpoints=[],
        max_turns=2,
        success_checks=SuccessChecks(
            expect_interrupt=True, expect_handoff_reason="policy_requires_human"
        ),
    )
    s_cap = _sample_scenario(
        id="s-cap",
        category="policy_qa",
        expected_outcome="answer",
        expected_tool_calls=[],
        checkpoints=[],
        max_turns=2,
        success_checks=SuccessChecks(),
    )

    sim_model = FakeListChatModel(
        responses=[
            "What is the return window? [DONE]",
            "I want a refund for my recent order.",
            "Tell me about returns.",
            "Tell me more about returns.",
        ]
    )
    simulator = UserSimulator(sim_model, model_name="fake-sim")

    fast_model = _StructuredFake(
        responses=["Rewrite query", "Rewrite query", "Rewrite query", "Rewrite query"],
        payloads=[
            {"intent": "policy_question", "confidence": 0.99},
            {"intent": "refund_request", "confidence": 0.99},
            {"intent": "policy_question", "confidence": 0.99},
            {"intent": "policy_question", "confidence": 0.99},
        ],
    )
    answer_payload = {
        "parts": [
            {
                "question": "What is the return window?",
                "supported": True,
                "explicit": True,
                "answer": "Returns are accepted within 30 days of delivery.",
                "evidence": [{"source": 1, "quote": "returns are accepted within 30 days"}],
            }
        ]
    }
    decision_payload = {
        "eligible": "needs_human",
        "reasons": ["Requires manual check [1]."],
        "item_ids": [],
        "citations": [1],
    }
    main_model = _StructuredFake(
        responses=["ok"],
        payloads=[answer_payload, decision_payload, answer_payload, answer_payload],
    )

    graph_deps = GraphDeps(
        settings=settings,
        fast_model=fast_model,
        main_model=main_model,
        retriever=retriever,
        order_service=order_service,
        allow_untuned_gate=True,
    )
    try:
        transcripts = asyncio.run(
            run_suite(
                settings,
                [s_policy, s_interrupt, s_cap],
                simulator=simulator,
                graph_deps=graph_deps,
                order_service=order_service,
                repeats=1,
            )
        )
    finally:
        order_service.close()

    by_id = {tr.scenario_id: tr for tr in transcripts}
    assert by_id["s-policy"].stop_reason == "done"
    assert len(by_id["s-policy"].turns) == 1
    assert "30 days" in by_id["s-policy"].turns[0].agent_message

    assert by_id["s-interrupt"].turns[0].interrupt_prompt is not None
    assert by_id["s-interrupt"].turns[0].resume_choice == recent_order_id
    assert by_id["s-interrupt"].turns[0].handoff_reason == "policy_requires_human"

    assert by_id["s-cap"].stop_reason == "max_turns"
    assert len(by_id["s-cap"].turns) == 2

    evals = [evaluate_transcript(sc, by_id[sc.id]) for sc in (s_policy, s_interrupt, s_cap)]
    agg = aggregate_evaluations(evals, n_resamples=100, seed=27)
    report_md = render_sim_report(
        settings,
        agg,
        dataset_version="v1",
        split="test",
        subset="all",
        repeats=1,
        simulator_model="fake-sim",
    )
    assert "Multi-turn simulation baseline report" in report_md
    assert "Tokens per turn curve" in report_md
    validity_md = render_validity_template(transcripts, sample_size=10)
    assert "Simulator validity review" in validity_md


def test_a_checkpoint_after_the_last_turn_is_not_reached_and_not_a_miss() -> None:
    # The script asks for recall at turn 5; the simulated user said goodbye at turn 2.
    scenario = _sample_scenario(
        checkpoints=[
            FactCheckpoint(turn_hint=2, fact_key="order_id", expected_substrings=["ORD-000009"]),
            FactCheckpoint(turn_hint=5, fact_key="order_id", expected_substrings=["ORD-000009"]),
        ]
    )
    turns = [
        SimTurn(turn_index=1, user_message="Check ORD-000009.", agent_message="In transit."),
        SimTurn(
            turn_index=2, user_message="Thanks, bye.", agent_message="ORD-000009 is on its way."
        ),
    ]
    short = ConversationTranscript(
        scenario_id=scenario.id, category=scenario.category, customer_id="CUST-0001", turns=turns
    )
    ev = evaluate_transcript(scenario, short)
    assert ev.fact_retention == 1.0
    assert (ev.fact_checkpoints, ev.fact_checkpoints_reached) == (2, 1)

    none_reached = ConversationTranscript(
        scenario_id=scenario.id,
        category=scenario.category,
        customer_id="CUST-0001",
        turns=turns[:1],
    )
    ev_none = evaluate_transcript(
        _sample_scenario(
            checkpoints=[
                FactCheckpoint(turn_hint=5, fact_key="order_id", expected_substrings=["X"])
            ]
        ),
        none_reached,
    )
    assert ev_none.fact_retention is None
    agg = aggregate_evaluations([ev, ev_none], n_resamples=50, seed=27)
    assert agg["fact_checkpoints"] == {"reached": 1, "total": 3}
    assert agg["fact_retention"]["n"] == 1


def test_rescore_reports_reached_checkpoints_from_saved_transcripts(tmp_path: Path) -> None:
    from eval.sim import rescore

    scenario = load_scenarios(rescore.SCENARIOS)[0]
    run = tmp_path / "sim-test-x"
    run.mkdir()
    transcript = ConversationTranscript(
        scenario_id=scenario.id,
        category=scenario.category,
        customer_id=scenario.customer_id,
        turns=[SimTurn(turn_index=1, user_message="hi", agent_message="hello")],
    )
    (run / "items.jsonl").write_text(transcript.model_dump_json() + "\n")
    text = rescore.render([run])
    assert "| `sim-test-x` |" in text
    assert f"0/{len(scenario.checkpoints)}" in text


def _scripted_run(
    tmp_path: Path, sim_replies: list[str], chunks: list[RetrievedChunk], checkpoint_turn: int
) -> ConversationTranscript:
    settings: Settings = get_settings().model_copy(deep=True)
    settings.orders.db_path = str(tmp_path / "orders.sqlite")
    settings.planning.enabled = False
    settings.grounding.enabled = False
    settings.cache.enabled = False
    settings.api.rate_limit.per_customer = 1000
    settings.api.rate_limit.per_ip = 1000
    seed_orders(settings)
    order_service = OrderService(platform=settings)
    scenario = _sample_scenario(
        id="s-scripted",
        category="topic_switch",
        expected_outcome="answer",
        expected_tool_calls=[],
        script_hints=[f"Turn {checkpoint_turn}: ask about the return window again."],
        checkpoints=[
            FactCheckpoint(
                turn_hint=checkpoint_turn, fact_key="order_id", expected_substrings=["30"]
            )
        ],
        max_turns=5,
    )
    n = len(sim_replies)
    fast_model = _StructuredFake(
        responses=["Rewrite query"] * n,
        payloads=[{"intent": "policy_question", "confidence": 0.99}] * n,
    )
    answer = {
        "parts": [
            {
                "question": "What is the return window?",
                "supported": True,
                "explicit": True,
                "answer": "Returns are accepted within 30 days of delivery.",
                "evidence": [{"source": 1, "quote": "returns are accepted within 30 days"}],
            }
        ]
    }
    graph_deps = GraphDeps(
        settings=settings,
        fast_model=fast_model,
        main_model=_StructuredFake(responses=["ok"], payloads=[answer] * n),
        retriever=_StaticRetriever(chunks),
        order_service=order_service,
        allow_untuned_gate=True,
    )
    simulator = UserSimulator(FakeListChatModel(responses=sim_replies), model_name="fake-sim")
    try:
        [transcript] = asyncio.run(
            run_suite(
                settings,
                [scenario],
                simulator=simulator,
                graph_deps=graph_deps,
                order_service=order_service,
                repeats=1,
            )
        )
    finally:
        order_service.close()
    return transcript


def test_scripted_chat_ignores_an_early_done_until_its_last_checkpoint(tmp_path: Path) -> None:
    chunks = [_chunk("Generic store returns are accepted within 30 days of delivery.")]
    transcript = _scripted_run(
        tmp_path,
        [
            "What is the return window?",
            "Thanks, that is all. [DONE]",
            "Sorry, what was the return window again? [DONE]",
        ],
        chunks,
        checkpoint_turn=3,
    )
    assert [t.turn_index for t in transcript.turns] == [1, 2, 3]
    assert transcript.early_done_ignored == [2]
    assert transcript.stop_reason == "done"


def test_scripted_chat_continues_past_a_handoff_until_its_last_checkpoint(tmp_path: Path) -> None:
    # No evidence: every policy turn hands off, but the script still probes turn 2.
    transcript = _scripted_run(
        tmp_path,
        ["What is the return window?", "And what about exchanges? [DONE]"],
        [],
        checkpoint_turn=2,
    )
    assert transcript.turns[0].handoff_reason is not None
    assert [t.turn_index for t in transcript.turns] == [1, 2]


def test_simulator_brief_names_this_turns_script_and_the_last_checkpoint() -> None:
    from eval.sim.user import _scenario_brief, hint_for_turn, scripted_turns

    scenario = _sample_scenario(
        script_hints=["Turn 1: ask status.", "Turns 2-4: ask about returns.", "Turn 5: recap."],
        checkpoints=[
            FactCheckpoint(turn_hint=5, fact_key="order_id", expected_substrings=["ORD-000009"])
        ],
    )
    assert scripted_turns(scenario) == 5
    assert hint_for_turn(scenario, 3) == "ask about returns."
    assert hint_for_turn(scenario, 6) is None
    brief = json.loads(_scenario_brief(scenario, 5))
    assert brief["current_script_hint"] == "recap."
    assert brief["must_not_finish_before_turn"] == 5


def test_an_empty_done_at_the_checkpoint_turn_still_sends_the_probe(tmp_path: Path) -> None:
    chunks = [_chunk("Generic store returns are accepted within 30 days of delivery.")]
    transcript = _scripted_run(
        tmp_path,
        ["What is the return window?", "[DONE]", "What was the window again? [DONE]"],
        chunks,
        checkpoint_turn=2,
    )
    assert [t.turn_index for t in transcript.turns] == [1, 2]
    assert transcript.turns[1].user_message == "What was the window again?"
    assert transcript.early_done_ignored == [2]


def test_scripted_brief_shows_only_the_current_step() -> None:
    from eval.sim.user import FILLER_STEP, _scenario_brief

    scripted = _sample_scenario(
        script_hints=["Turn 1: ask status.", "Turn 3: recap."],
        checkpoints=[
            FactCheckpoint(turn_hint=3, fact_key="order_id", expected_substrings=["ORD-000009"])
        ],
    )
    brief = json.loads(_scenario_brief(scripted, 2))
    assert "script_hints" not in brief
    assert brief["current_script_hint"] == FILLER_STEP
    assert json.loads(_scenario_brief(scripted, 4))["current_script_hint"] is None
    free = _sample_scenario(script_hints=["Turn 1: ask status."], checkpoints=[])
    assert json.loads(_scenario_brief(free, 1))["script_hints"] == ["Turn 1: ask status."]


def test_a_probe_that_restates_the_fact_is_not_scored_as_recall() -> None:
    scenario = _sample_scenario(
        checkpoints=[
            FactCheckpoint(turn_hint=2, fact_key="order_id", expected_substrings=["ORD-000009"])
        ]
    )
    transcript = ConversationTranscript(
        scenario_id=scenario.id,
        category=scenario.category,
        customer_id="CUST-0001",
        turns=[
            SimTurn(turn_index=1, user_message="Check ORD-000009.", agent_message="In transit."),
            SimTurn(
                turn_index=2,
                user_message="Confirm ORD-000009 for me?",
                agent_message="ORD-000009 is in transit.",
            ),
        ],
    )
    ev = evaluate_transcript(scenario, transcript)
    assert ev.fact_retention is None
    assert ev.fact_checkpoints_reached == 0


def test_after_a_handoff_the_customer_is_told_the_assistant_is_still_there() -> None:
    from eval.sim.user import AFTER_HANDOFF
    from langchain_core.messages import BaseMessage

    seen: list[list[BaseMessage]] = []

    class _Recorder(FakeListChatModel):
        def invoke(self, messages: Any, *args: Any, **kwargs: Any) -> Any:
            seen.append(list(messages))
            return super().invoke(messages, *args, **kwargs)

    scenario = _sample_scenario(
        script_hints=["Turn 3: ask which order we discussed."],
        checkpoints=[
            FactCheckpoint(turn_hint=3, fact_key="order_id", expected_substrings=["ORD-000009"])
        ],
    )
    sim = UserSimulator(_Recorder(responses=["Which order was it?"]), model_name="fake")
    history = [("user", "Check ORD-000009."), ("assistant", "I'll pass you to a human.")]
    sim.next_turn(scenario, history, 3, after_handoff=True)  # type: ignore[arg-type]
    note = str(seen[-1][-1].content)
    assert note == AFTER_HANDOFF.format(hint="ask which order we discussed.")
