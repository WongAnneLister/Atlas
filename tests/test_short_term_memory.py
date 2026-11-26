"""Offline tests for short-term memory: pinned facts, chunked compaction, and 30-turn stability."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from support_agent.config import get_settings
from support_agent.context.builder import ContextBuilder
from support_agent.context.settings import ContextSettings
from support_agent.graph.deps import GraphDeps
from support_agent.graph.nodes.refund import RefundPath
from support_agent.graph.state import ConversationState
from support_agent.memory.settings import ShortTermMemorySettings
from support_agent.memory.short_term.compaction import (
    SummaryBlock,
    compact_history,
    group_into_turns,
    validate_summary_numbers,
)
from support_agent.memory.short_term.facts import PinnedFacts, extract_facts_from_turn
from support_agent.orders.seed import seed_orders
from support_agent.orders.service import OrderService


def test_pinned_facts_extraction_supersede_and_deterministic_render() -> None:
    facts = PinnedFacts()
    facts = extract_facts_from_turn(
        "Check ORD-001042 for my BHD340/10 bought on 2026-10-01 for $49.99.", 1, facts
    )
    assert facts.latest_order_id() == "ORD-001042"
    assert [f.value for f in facts.active("model_number")] == ["BHD340/10"]
    assert [f.value for f in facts.active("date")] == ["2026-10-01"]
    assert [f.value for f in facts.active("amount")] == ["$49.99"]

    # Correction supersedes old order ID while keeping history of the correction.
    facts = extract_facts_from_turn("Sorry, I meant ORD-001043 instead.", 2, facts)
    assert facts.latest_order_id() == "ORD-001043"
    assert [f.value for f in facts.active("order_id")] == ["ORD-001043"]
    rendered = facts.render_dict()
    assert rendered["current"]["order_id"] == [{"value": "ORD-001043", "turn": 2}]
    assert "order_id: ORD-001042 superseded by ORD-001043" in rendered["corrections"]
    # Deterministic rendering across repeated calls.
    assert facts.render_dict() == rendered


def test_compaction_triggers_whole_chunks_keeps_tool_pairs_and_respects_watermark() -> None:
    # Build history with a tool call/result pair inside turn 2.
    history: list[BaseMessage] = []
    for t in range(1, 9):
        history.append(HumanMessage(content=f"Turn {t}: checking policy detail " + "word " * 25))
        if t == 2:
            history.append(
                AIMessage(
                    content="",
                    tool_calls=[
                        {"id": "tc1", "name": "get_order", "args": {"order_id": "ORD-000001"}}
                    ],
                )
            )
            history.append(ToolMessage(content='{"order_id":"ORD-000001"}', tool_call_id="tc1"))
        history.append(AIMessage(content=f"Turn {t} reply with details " + "info " * 25))

    groups = group_into_turns(history)
    assert len(groups) == 8
    # Tool call and ToolMessage stay inside the same atomic turn group.
    assert any(isinstance(m, ToolMessage) for m in groups[1])
    assert sum(1 for m in groups[1] if isinstance(m, AIMessage)) == 2

    # Below budget -> no compaction.
    high_budget = ShortTermMemorySettings(history_budget=50000, chunk_turns=3, low_watermark=0.6)
    no_op = compact_history(
        history, active_history_start=0, existing_blocks=[], current_turn=9, settings=high_budget
    )
    assert no_op.compacted_chunks == 0
    assert no_op.active_history_start == 0
    assert no_op.blocks == []

    # Above budget -> compacts whole chunks down to low watermark, then next turn does NOT fire.
    tight = ShortTermMemorySettings(history_budget=350, chunk_turns=3, low_watermark=0.6)
    res1 = compact_history(
        history, active_history_start=0, existing_blocks=[], current_turn=9, settings=tight
    )
    assert res1.compacted_chunks >= 1
    assert res1.active_history_start > 0
    assert len(res1.blocks) == res1.compacted_chunks

    # Adding one small turn stays below budget -> hysteresis prevents immediate re-compaction.
    next_hist = [*history, HumanMessage(content="Thanks!"), AIMessage(content="You're welcome.")]
    res2 = compact_history(
        next_hist,
        active_history_start=res1.active_history_start,
        existing_blocks=res1.blocks,
        current_turn=10,
        settings=tight,
    )
    assert res2.compacted_chunks == 0
    assert res2.blocks == res1.blocks


def test_existing_summary_blocks_are_immutable_and_second_level_merges_when_over_budget() -> None:
    b0 = SummaryBlock(
        block_id="blk-1-3", turns=(1, 3), text="- Asked about ORD-000001.", created_at_turn=4
    )
    before_hash = hashlib.sha256(b0.model_dump_json().encode()).hexdigest()

    history: list[BaseMessage] = []
    for t in range(4, 12):
        history.append(HumanMessage(content=f"Turn {t} question " + "detail " * 30))
        history.append(AIMessage(content=f"Turn {t} answer " + "fact " * 30))

    cfg = ShortTermMemorySettings(
        history_budget=300, summary_budget=5000, chunk_turns=3, low_watermark=0.6
    )
    res = compact_history(
        history, active_history_start=0, existing_blocks=[b0], current_turn=12, settings=cfg
    )
    assert len(res.blocks) >= 2
    after_hash = hashlib.sha256(res.blocks[0].model_dump_json().encode()).hexdigest()
    assert after_hash == before_hash

    # Tight summary_budget triggers second-level merge of oldest blocks.
    merge_cfg = ShortTermMemorySettings(
        history_budget=300, summary_budget=15, chunk_turns=3, low_watermark=0.6
    )
    merged = compact_history(
        history, active_history_start=0, existing_blocks=[b0], current_turn=12, settings=merge_cfg
    )
    assert merged.second_level_merges >= 1


def test_invalid_summary_retries_then_falls_back_to_extractive_and_reuses_l0_l2_prefix() -> None:
    assert validate_summary_numbers("Refund for ORD-999999", "Refund for ORD-000001") == [
        "ORD-999999"
    ]
    assert validate_summary_numbers("Refund for ORD-000001", "Refund for ORD-000001") == []

    seen_calls: list[list[Any]] = []

    class RecordingBadSummariser(FakeListChatModel):
        def invoke(self, input: Any, *args: Any, **kwargs: Any) -> Any:
            seen_calls.append(list(input))
            return super().invoke(input, *args, **kwargs)

    # Both attempts invent number 99999 -> must retry once (2 calls) then fall back to extractive.
    bad_model = RecordingBadSummariser(
        responses=[
            "- Customer asked about ORD-000001 and refund 99999.",
            "- Still mentions invented 88888.",
        ]
    )
    settings = get_settings().model_copy(deep=True)
    settings.memory.short_term.history_budget = 100
    settings.memory.short_term.chunk_turns = 2
    settings.memory.short_term.low_watermark = 0.5
    b0 = SummaryBlock(block_id="blk-1-2", turns=(1, 2), text="- Earlier block.", created_at_turn=3)

    history: list[BaseMessage] = []
    for t in range(3, 8):
        history.append(HumanMessage(content=f"Turn {t}: checking ORD-000001 " + "text " * 25))
        history.append(AIMessage(content=f"Turn {t}: status delivered " + "info " * 25))

    with GraphDeps(settings=settings, fast_model=bad_model) as deps:
        builder = deps.context_builder()
        # A main-conversation node that keeps the builder layout (answer uses the legacy one).
        parent_l0_l2 = builder.build(
            "tools",
            task_prompt="Answer.",
            user_text="Current?",
            compacted_blocks=[b0.text],
            history=(),
        )
        res = compact_history(
            history,
            active_history_start=0,
            existing_blocks=[b0],
            current_turn=8,
            settings=settings.memory.short_term,
            models=deps.models,
            builder=builder,
        )

    assert res.summariser_calls >= 2
    assert res.extractive_fallbacks >= 1
    assert res.blocks[1].extractive_fallback is True
    assert "ORD-000001" in res.blocks[1].text
    # First summariser request started with exact parent L0..L2 messages!
    first_req = seen_calls[0]
    assert [(m.type, m.content) for m in first_req[:2]] == [
        (m.type, m.content) for m in parent_l0_l2.messages[:2]
    ]


def test_prefix_stability_across_30_turns_changes_only_at_compaction() -> None:
    ctx_settings = ContextSettings(hard_history_turn_cap=50)
    st_settings = ShortTermMemorySettings(
        history_budget=400, summary_budget=5000, chunk_turns=6, low_watermark=0.6
    )
    builder = ContextBuilder(ctx_settings)

    all_history: list[BaseMessage] = []
    blocks: list[SummaryBlock] = []
    start_idx = 0
    compaction_turns: list[int] = []
    prev_l0_l2: list[tuple[str, object]] = []
    prev_prefix: list[tuple[str, object]] = []

    for turn in range(1, 31):
        comp = compact_history(
            all_history,
            active_history_start=start_idx,
            existing_blocks=blocks,
            current_turn=turn,
            settings=st_settings,
            builder=builder,
        )
        compacted_this_turn = comp.compacted_chunks > 0
        if compacted_this_turn:
            compaction_turns.append(turn)
        blocks = comp.blocks
        start_idx = comp.active_history_start

        built = builder.build(
            "answer",
            task_prompt="Answer using sources.",
            user_text=f"Turn {turn} question?",
            compacted_blocks=[b.text for b in blocks],
            history=all_history[start_idx:],
        )
        cur_prefix = [(m.type, m.content) for m in built.messages[: built.prefix_message_count]]
        l0_l2_count = 1 + len(blocks)
        cur_l0_l2 = cur_prefix[:l0_l2_count]

        if prev_prefix and not compacted_this_turn:
            # Between compaction turns: L0..L2 is byte-identical and L3 is strictly append-only!
            assert cur_l0_l2 == prev_l0_l2
            assert cur_prefix[: len(prev_prefix)] == prev_prefix

        prev_l0_l2 = cur_l0_l2
        prev_prefix = cur_prefix
        all_history.append(HumanMessage(content=f"Turn {turn} user message " + "filler " * 10))
        all_history.append(AIMessage(content=f"Turn {turn} agent reply " + "answer " * 10))

    assert len(compaction_turns) >= 2
    assert len(compaction_turns) < 10


def test_pinned_order_id_survives_30_turns_and_refund_uses_it_without_asking(
    tmp_path: Path,
) -> None:
    settings = get_settings().model_copy(deep=True)
    settings.orders.db_path = str(tmp_path / "orders.sqlite")
    seed_orders(settings)

    facts = extract_facts_from_turn("Please check my order ORD-000001.", 1, PinnedFacts())
    for turn in range(2, 31):
        facts = extract_facts_from_turn(f"Turn {turn}: general shipping question?", turn, facts)

    assert facts.latest_order_id() == "ORD-000001"

    service = OrderService(platform=settings)
    try:
        with GraphDeps(settings=settings, order_service=service) as deps:
            refund = RefundPath(deps)
            state = ConversationState(
                customer_id="CUST-0001",
                messages=[HumanMessage(content="I want a refund please.")],
                pinned_facts=facts,
            )
            update = refund.identify_order(state)
    finally:
        service.close()

    assert update["refund_order_id"] == "ORD-000001"
