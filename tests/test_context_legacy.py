"""`context.enabled: false` restores the message layout from before the ContextBuilder."""

from __future__ import annotations

from datetime import date
from typing import Any

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableLambda

from support_agent.cache.keys import prompt_version_hash
from support_agent.config import get_settings
from support_agent.context.builder import ContextBuilder
from support_agent.context.sections import SHARED_L0_PREAMBLE, render_shared_l0
from support_agent.context.settings import ContextSettings, NodeBudgetProfile
from support_agent.graph.build import build_graph
from support_agent.graph.deps import GraphDeps
from support_agent.graph.handoff import PROMPTS, HandoffReason
from support_agent.retrieval.types import RetrievedChunk
from test_context_builder import _chunk


def _legacy_builder() -> ContextBuilder:
    settings = ContextSettings(enabled=False)
    # A tiny budget proves the legacy layout never trims and never overflows.
    settings.profiles["answer"] = NodeBudgetProfile(total_tokens=5, share_prefix=True)
    return ContextBuilder(settings, llm_provider="deepseek")


def test_disabled_builder_sends_only_the_task_prompt_and_the_input() -> None:
    built = _legacy_builder().build(
        "answer",
        task_prompt="ANSWER PROMPT",
        user_text="question and numbered sources",
        history=[HumanMessage(content="earlier"), AIMessage(content="reply")],
        customer_profile="Owns a W40.",
        compacted_blocks=["summary"],
        pinned_facts={"model_number": [{"value": "W40", "turn": 1}]},
        current_date=date(2026, 11, 9),
    )
    assert built.messages == [
        SystemMessage(content="ANSWER PROMPT"),
        HumanMessage(content="question and numbered sources"),
    ]


def test_disabled_builder_keeps_tool_loop_and_rewrite_turns() -> None:
    builder = _legacy_builder()
    loop: list[BaseMessage] = [
        AIMessage(content="", tool_calls=[{"name": "get_order", "args": {}, "id": "t1"}]),
        ToolMessage(content="{}", tool_call_id="t1"),
    ]
    tools = builder.build(
        "tools", task_prompt="TOOLS", user_text="where is it?", extra_l4_messages=loop
    )
    assert tools.messages == [
        SystemMessage(content="TOOLS"),
        HumanMessage(content="where is it?"),
        *loop,
    ]

    turns = [
        HumanMessage(content="I bought a W40."),
        AIMessage(content="OK."),
        HumanMessage(content="Return it?"),
    ]
    rewrite = builder.build(
        "rewrite",
        task_prompt="REWRITE",
        user_text="Return it?",
        history=turns[:-1],
        legacy_turns=turns,
    )
    assert rewrite.messages == [SystemMessage(content="REWRITE"), *turns]


def test_preamble_file_is_what_the_enabled_builder_sends() -> None:
    text = (PROMPTS / "global_preamble.md").read_text(encoding="utf-8").rstrip("\n")
    assert text == SHARED_L0_PREAMBLE
    assert render_shared_l0([]) == text


def test_answer_cache_version_changes_with_the_context_layout() -> None:
    on = get_settings().model_copy(deep=True)
    off = on.model_copy(deep=True)
    off.context.enabled = False
    assert prompt_version_hash(PROMPTS, on) != prompt_version_hash(PROMPTS, off)


def test_graph_answer_call_uses_the_legacy_layout_and_never_overflows() -> None:
    class _ClassifyFake(FakeListChatModel):
        def with_structured_output(self, schema: Any, **kwargs: object) -> object:
            payload = {"intent": "policy_question", "confidence": 0.99}
            return RunnableLambda(
                lambda _: {
                    "parsed": schema.model_validate(payload),
                    "raw": None,
                    "parsing_error": None,
                }
            )

    seen: list[list[BaseMessage]] = []

    class _AnswerRecorder(FakeListChatModel):
        def with_structured_output(self, schema: Any, **kwargs: object) -> object:
            def record(messages: list[BaseMessage]) -> dict[str, Any]:
                seen.append(list(messages))
                return {"parsed": None, "raw": None, "parsing_error": ValueError("stop here")}

            return RunnableLambda(record)

    class _Retriever:
        def supports_filters(self) -> bool:
            return True

        def retrieve(self, query: str, top_k: int, filters: object = None) -> list[RetrievedChunk]:
            return [_chunk(1, "Returns are accepted within 30 days.")]

    settings = get_settings().model_copy(deep=True)
    settings.context.enabled = False
    settings.planning.enabled = False
    settings.grounding.enabled = False
    settings.cache.enabled = False
    # This budget handed off with ContextOverflow when the builder was enabled.
    settings.context.profiles["answer"] = NodeBudgetProfile(total_tokens=20, share_prefix=True)
    deps = GraphDeps(
        settings=settings,
        fast_model=_ClassifyFake(responses=["ok"]),
        main_model=_AnswerRecorder(responses=["ok"]),
        retriever=_Retriever(),
        allow_untuned_gate=True,
    )
    try:
        result = build_graph(deps).invoke(
            {
                "messages": [HumanMessage(content="What is the return window?")],
                "customer_id": "CUST-1",
            },
            {"configurable": {"thread_id": "legacy-1"}},
        )
    finally:
        deps.close()
    assert result["handoff"] is None or result["handoff"].reason != HandoffReason.CONTEXT_OVERFLOW
    assert seen, "the answer model was never called"
    first = seen[0]
    assert [type(m) for m in first] == [SystemMessage, HumanMessage]
    assert not str(first[0].content).startswith(SHARED_L0_PREAMBLE[:20])
    assert "Returns are accepted within 30 days." in str(first[1].content)


def test_one_node_can_use_the_legacy_layout_while_others_keep_the_builder() -> None:
    settings = ContextSettings()
    settings.profiles["answer"] = settings.profiles["answer"].model_copy(
        update={"legacy_layout": True}
    )
    builder = ContextBuilder(settings, llm_provider="deepseek")
    answer = builder.build(
        "answer", task_prompt="ANSWER", user_text="data", current_date="2026-11-09"
    )
    assert answer.messages == [SystemMessage(content="ANSWER"), HumanMessage(content="data")]
    tools = builder.build("tools", task_prompt="TOOLS", user_text="where?")
    assert tools.messages[0].content == SHARED_L0_PREAMBLE
