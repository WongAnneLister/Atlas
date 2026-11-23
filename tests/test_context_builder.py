"""Offline tests for ContextBuilder prefix stability, budgets, compressors, and cache adapter."""

from __future__ import annotations

import random
from datetime import date

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableLambda

from support_agent.config import REPO_ROOT, get_settings
from support_agent.context.budget import ContextOverflow
from support_agent.context.builder import ContextBuilder
from support_agent.context.cache_adapter import Breakpoint, apply_cache_breakpoints
from support_agent.context.sections import (
    canonical_json,
    compress_tool_result,
    render_shared_l0,
)
from support_agent.context.settings import CacheAdapterSettings, ContextSettings, NodeBudgetProfile
from support_agent.graph.build import build_graph
from support_agent.graph.deps import GraphDeps
from support_agent.graph.handoff import HandoffReason
from support_agent.retrieval.types import RetrievedChunk


def _chunk(idx: int, text: str, score: float = 0.9) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"c-{idx}",
        doc_id="returns",
        title="Returns",
        section_id=f"returns.sec.{idx}",
        heading_path=f"Returns > Section {idx}",
        text=text,
        n_tokens=len(text.split()),
        scores={"rerank": score, "rerank_logit": score * 3.0},
        ranks={"rerank": idx},
    )


def test_prefix_stability_across_12_turns_and_shared_l0_across_nodes() -> None:
    settings = ContextSettings(hard_history_turn_cap=16)
    builder = ContextBuilder(settings, llm_provider="deepseek")

    # Shared L0 bytes are byte-identical across all main-conversation nodes, dates, and customers.
    l0_hashes = set()
    for node in ("rewrite", "answer", "tools", "decide", "complaint"):
        built = builder.build(
            node,
            task_prompt=f"Specific instructions for {node}",
            user_text="Question",
            current_date=date(2026, 11, 23),
        )
        l0_hashes.add(built.l0_hash)
    assert len(l0_hashes) == 1

    # Simulate 12 consecutive turns: rendered L0..L3 of turn n is an append-only prefix of turn n+1.
    history: list[BaseMessage] = []
    prev_prefix_msgs: list[tuple[str, object]] = []
    for turn in range(1, 13):
        built = builder.build(
            "answer",
            task_prompt="Answer using sources.",
            user_text=f"Turn {turn} question?",
            history=history,
            current_date=date(2026, 11, 9),
        )
        cur_prefix_msgs = [
            (m.type, m.content) for m in built.messages[: built.prefix_message_count]
        ]
        if prev_prefix_msgs:
            assert cur_prefix_msgs[: len(prev_prefix_msgs)] == prev_prefix_msgs
            assert len(cur_prefix_msgs) == len(prev_prefix_msgs) + 2
        prev_prefix_msgs = cur_prefix_msgs
        history.append(HumanMessage(content=f"Turn {turn} question?"))
        history.append(AIMessage(content=f"Turn {turn} answer [1]."))


def test_silent_invalidator_guards() -> None:
    assert render_shared_l0(["get_tracking", "get_order", "get_order"]) == render_shared_l0(
        ["get_order", "get_tracking"]
    )
    assert canonical_json({"b": 1, "a": {"y": 2, "x": 3}}) == canonical_json(
        {"a": {"x": 3, "y": 2}, "b": 1}
    )

    builder = ContextBuilder(ContextSettings())
    b1 = builder.build(
        "answer", task_prompt="Prompt A", user_text="Hi", current_date=date(2026, 1, 1)
    )
    b2 = builder.build(
        "answer", task_prompt="Prompt B", user_text="Bye", current_date=date(2026, 12, 31)
    )
    assert b1.l0_hash == b2.l0_hash
    assert b1.prefix_hash == b2.prefix_hash


def test_budget_l4_only_trimming_breakdown_sum_and_overflow() -> None:
    rng = random.Random(28)
    for _trial in range(15):
        budget = rng.randint(250, 600)
        settings = ContextSettings(
            profiles={
                "answer": NodeBudgetProfile(
                    total_tokens=budget,
                    history_max_tokens=100,
                    evidence_min_ratio=0.40,
                    share_prefix=True,
                )
            }
        )
        builder = ContextBuilder(settings)
        history = [HumanMessage(content="Earlier turn"), AIMessage(content="Earlier reply [1].")]
        chunks = [
            _chunk(i, ("policy fact " * rng.randint(10, 40)).strip(), score=0.95 - i * 0.1)
            for i in range(1, 6)
        ]
        built = builder.build(
            "answer",
            task_prompt="Answer strictly from sources.",
            user_text="What is the return policy?",
            history=history,
            evidence=chunks,
            good_evidence_count=0,
            tool_results=[("get_order", {"order_id": "ORD-000001", "status": "delivered"})],
            current_date=date(2026, 11, 9),
        )
        bd = built.breakdown
        assert bd.total_tokens <= budget
        assert sum(bd.by_layer.values()) == bd.total_tokens
        assert sum(bd.by_section.values()) == bd.total_tokens
        # Trimming never touches L0..L3.
        assert all(d.section not in {"system_instructions", "recent_turns"} for d in bd.dropped)

    # Overflow when never-trim sections exceed budget.
    tiny = ContextSettings(
        profiles={"answer": NodeBudgetProfile(total_tokens=40, share_prefix=True)}
    )
    with pytest.raises(ContextOverflow):
        ContextBuilder(tiny).build(
            "answer",
            task_prompt="Answer from sources.",
            user_text="What is the return policy?",
        )

    # Overflow when good_evidence_count chunks cannot fit.
    tight = ContextSettings(
        profiles={"answer": NodeBudgetProfile(total_tokens=180, share_prefix=True)}
    )
    huge_chunks = [_chunk(1, "word " * 300), _chunk(2, "word " * 300)]
    with pytest.raises(ContextOverflow):
        ContextBuilder(tight).build(
            "answer",
            task_prompt="Answer.",
            user_text="Question?",
            evidence=huge_chunks,
            good_evidence_count=2,
        )


def test_tool_result_compressor_keeps_refund_decision_fields() -> None:
    fixture_order = {
        "order_id": "ORD-000001",
        "status": "delivered",
        "order_date": "2026-11-01",
        "delivered_date": "2026-11-04",
        "days_since_order": 8,
        "days_since_delivery": 5,
        "currency": "USD",
        "total": "49.99",
        "coupon_code": "DEMO10",
        "internal_debug_blob": "x" * 2000,
        "items": [
            {
                "item_id": "ITEM-1",
                "product_id": "demo-w40",
                "model": "W40",
                "quantity": 1,
                "unit_price": "49.99",
                "final_sale": False,
                "refunded_quantity": 0,
                "warehouse_notes": "y" * 1000,
            }
        ],
    }
    compressed = compress_tool_result("get_order", fixture_order)
    for required in (
        "ORD-000001",
        "delivered",
        "2026-11-01",
        "days_since_delivery",
        "49.99",
        "DEMO10",
        "ITEM-1",
        "final_sale",
        "refunded_quantity",
    ):
        assert required in compressed
    assert "internal_debug_blob" not in compressed
    assert "warehouse_notes" not in compressed


def test_cache_adapter_breakpoints_and_noop_providers() -> None:
    msgs = [
        HumanMessage(content="m0"),
        HumanMessage(content="m1"),
        HumanMessage(content="m2"),
        HumanMessage(content="m3"),
    ]
    bps = [
        Breakpoint(layer="L0_global", message_index=0, prefix_tokens=500, ttl_s=3600),
        Breakpoint(layer="L1_session", message_index=1, prefix_tokens=1200, ttl_s=300),
        Breakpoint(layer="L2_compacted", message_index=2, prefix_tokens=1800, ttl_s=300),
        Breakpoint(layer="L3_history", message_index=3, prefix_tokens=2400, ttl_s=300),
    ]
    cfg = CacheAdapterSettings(provider="anthropic", max_breakpoints=2, min_cacheable_tokens=1024)
    adapted, active = apply_cache_breakpoints(msgs, bps, cfg, llm_provider="anthropic")
    # L0 (500 < 1024) skipped; 3 eligible capped to 2 (L1 + L3).
    assert len(active) == 2
    assert [bp.layer for bp in active] == ["L1_session", "L3_history"]
    assert isinstance(adapted[1].content, list)
    assert isinstance(adapted[3].content, list)
    assert adapted[0].content == "m0"

    # DeepSeek / OpenAI / none -> plain messages unchanged.
    plain, _ = apply_cache_breakpoints(
        msgs, bps, CacheAdapterSettings(provider="auto"), llm_provider="deepseek"
    )
    assert all(isinstance(m.content, str) for m in plain)


def test_graph_hands_off_on_context_overflow() -> None:
    class _ClassifyFake(FakeListChatModel):
        def with_structured_output(self, schema: object, **kwargs: object) -> object:
            return RunnableLambda(
                lambda _: {
                    "parsed": schema.model_validate(  # type: ignore[attr-defined]
                        {"intent": "policy_question", "confidence": 0.99}
                    ),
                    "raw": None,
                    "parsing_error": None,
                }
            )

    class _Retriever:
        def supports_filters(self) -> bool:
            return True

        def retrieve(self, query: str, top_k: int, filters: object = None) -> list[RetrievedChunk]:
            return [_chunk(1, "Returns are accepted within 30 days.")]

    settings = get_settings().model_copy(deep=True)
    settings.planning.enabled = False
    settings.grounding.enabled = False
    settings.cache.enabled = False
    settings.context.profiles["answer"] = NodeBudgetProfile(total_tokens=20, share_prefix=True)

    deps = GraphDeps(
        settings=settings,
        fast_model=_ClassifyFake(responses=["ok"]),
        main_model=FakeListChatModel(responses=["never reached"]),
        retriever=_Retriever(),
        allow_untuned_gate=True,
    )
    try:
        graph = build_graph(deps)
        result = graph.invoke(
            {
                "messages": [HumanMessage(content="What is the return window?")],
                "customer_id": "CUST-0001",
            },
            {"configurable": {"thread_id": "overflow-1"}},
        )
    finally:
        deps.close()
    assert result["handoff"] is not None
    assert result["handoff"].reason == HandoffReason.CONTEXT_OVERFLOW


def test_every_graph_model_call_uses_context_builder() -> None:
    """Guardrail test: no graph or grounding node may call ReliableModels without ContextBuilder."""
    targets = [
        *sorted((REPO_ROOT / "src" / "support_agent" / "graph" / "nodes").glob("*.py")),
        REPO_ROOT / "src" / "support_agent" / "graph" / "order_grounding.py",
        REPO_ROOT / "src" / "support_agent" / "grounding" / "verify.py",
        REPO_ROOT / "src" / "support_agent" / "grounding" / "compound.py",
    ]
    checked = 0
    for path in targets:
        text = path.read_text(encoding="utf-8")
        if "models.invoke(" in text or "models.structured(" in text:
            checked += 1
            assert "context_builder().build(" in text, (
                f"{path.relative_to(REPO_ROOT)} calls ReliableModels without ContextBuilder"
            )
    assert checked >= 10
