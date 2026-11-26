"""Offline tests for Commit 35: strategy hash sequences, cost decomposition, and KV skip."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from eval.context_ab import decompose_cost
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from support_agent.config import REPO_ROOT
from support_agent.context.builder import ContextBuilder
from support_agent.context.settings import ContextSettings
from support_agent.memory.settings import ShortTermMemorySettings
from support_agent.memory.short_term.compaction import SummaryBlock, compact_history


def _simulate_strategy(strategy: str, n_turns: int = 12) -> tuple[int, int]:
    """Return (prefix_breaks, l2_changes) across n_turns on a fixed fake conversation."""
    ctx_cfg = ContextSettings(
        strategy=strategy,  # type: ignore[arg-type]
        sliding_window_turns=3,
        hard_history_turn_cap=50,
    )
    st_cfg = ShortTermMemorySettings(
        enabled=(strategy != "sliding"),
        strategy="rolling" if strategy == "rolling" else "chunked",
        history_budget=180,
        summary_budget=5000,
        chunk_turns=3,
        low_watermark=0.5,
    )
    builder = ContextBuilder(ctx_cfg)
    history: list[BaseMessage] = []
    blocks: list[SummaryBlock] = []
    start = 0
    prev_prefix: list[tuple[str, object]] = []
    prev_l2: list[str] = []
    prefix_breaks = 0
    l2_changes = 0

    for turn in range(1, n_turns + 1):
        if strategy != "sliding" and history:
            comp = compact_history(
                history,
                active_history_start=start,
                existing_blocks=blocks,
                current_turn=turn,
                settings=st_cfg,
                builder=builder,
            )
            blocks = comp.blocks
            start = comp.active_history_start

        built = builder.build(
            "answer",
            task_prompt="Answer from sources.",
            user_text=f"Turn {turn} question?",
            compacted_blocks=[b.text for b in blocks],
            history=history[start:],
        )
        cur_prefix = [(m.type, m.content) for m in built.messages[: built.prefix_message_count]]
        cur_l2 = [b.text for b in blocks]
        if prev_prefix and cur_prefix[: len(prev_prefix)] != prev_prefix:
            prefix_breaks += 1
        if prev_l2 and cur_l2 != prev_l2:
            l2_changes += 1
        prev_prefix = cur_prefix
        prev_l2 = cur_l2
        history.append(HumanMessage(content=f"Turn {turn} customer message " + "word " * 15))
        history.append(AIMessage(content=f"Turn {turn} assistant reply " + "info " * 15))
    return prefix_breaks, l2_changes


def test_strategy_prefix_hash_sequences() -> None:
    sliding_breaks, _ = _simulate_strategy("sliding", n_turns=12)
    rolling_breaks, rolling_l2 = _simulate_strategy("rolling", n_turns=12)
    chunked_breaks, _ = _simulate_strategy("chunked", n_turns=12)

    # Sliding breaks the prefix on every single turn once window (3 turns) fills: >= 7 breaks.
    assert sliding_breaks >= 7
    # Rolling rewrites L2 repeatedly.
    assert rolling_l2 >= 2
    assert rolling_breaks >= 2
    # Chunked breaks prefix ONLY at compaction points (strictly fewer than sliding).
    assert 1 <= chunked_breaks < sliding_breaks


def test_cost_decomposition_math() -> None:
    calls: list[dict[str, Any]] = [
        {
            "input_tokens": 1000,
            "cache_read_tokens": 800,
            "cache_write_tokens": 0,
            "output_tokens": 100,
        },
        {
            "input_tokens": 500,
            "cache_read_tokens": 200,
            "cache_write_tokens": 100,
            "output_tokens": 50,
        },
    ]
    cached = decompose_cost(calls, cache_read_multiplier=0.1, cache_write_multiplier=1.0)
    assert cached["total_input_tokens"] == 1500.0
    assert cached["cache_read_tokens"] == 1000.0
    assert cached["cache_write_tokens"] == 100.0
    assert cached["uncached_input_tokens"] == 400.0
    assert cached["output_tokens"] == 150.0
    # 400 uncached + 100*1.0 write + 1000*0.1 read = 600.0
    assert cached["effective_input_units"] == 600.0
    assert abs(cached["cache_hit_ratio"] - (1000.0 / 1500.0)) < 1e-9

    nocache = decompose_cost(
        calls, cache_read_multiplier=0.1, cache_write_multiplier=1.0, ignore_cache_discount=True
    )
    assert nocache["effective_input_units"] == 1500.0


def test_kv_benchmark_skips_cleanly_without_gpu(monkeypatch: Any) -> None:
    script = REPO_ROOT / "bench" / "kv" / "run_kv_bench.py"
    spec = importlib.util.spec_from_file_location("run_kv_bench", script)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    monkeypatch.setattr(mod, "has_nvidia_gpu", lambda: False)
    result = mod.run_kv_benchmark(prompts_path=Path("nonexistent.jsonl"), vllm_url=None)
    assert result["status"] == "skipped"
    assert "no GPU" in result["reason"]


def test_stable_prefix_ignores_growing_history_and_tracks_compaction() -> None:
    from eval.context_ab import _prefix_change_rate
    from eval.sim.models import ConversationTranscript, SimTurn

    builder = ContextBuilder(ContextSettings(), llm_provider="deepseek")
    history: list[BaseMessage] = []
    calls = []
    for turn in range(1, 5):
        blocks = ["frozen summary"] if turn >= 4 else []
        built = builder.build(
            "tools", task_prompt="T", user_text=f"q{turn}", history=history, compacted_blocks=blocks
        )
        calls.append(
            {"node": "tools", "prefix_hash": built.prefix_hash, "stable_hash": built.stable_hash}
        )
        history = [*history, HumanMessage(content=f"q{turn}"), AIMessage(content=f"a{turn}")]
    # The full prefix changes every turn; only the compaction at turn 4 changes L0..L2.
    assert len({c["prefix_hash"] for c in calls}) == 4
    assert len({c["stable_hash"] for c in calls}) == 2
    transcript = ConversationTranscript(
        scenario_id="s",
        category="topic_switch",
        customer_id="CUST-0001",
        turns=[
            SimTurn(turn_index=i + 1, user_message="u", context_calls=[c])
            for i, c in enumerate(calls)
        ],
    )
    assert _prefix_change_rate([transcript]) == 1 / 3

    old = transcript.model_copy(deep=True)
    for turn in old.turns:
        turn.context_calls = [{"node": "tools", "prefix_hash": "x"}]
    assert _prefix_change_rate([old]) is None
