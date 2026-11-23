"""Resolve follow-up references while preserving the customer's original facts."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import Overwrite

from support_agent.config import Settings
from support_agent.graph.state import ConversationState
from support_agent.memory.short_term.compaction import compact_history
from support_agent.memory.short_term.facts import extract_facts_from_turn
from support_agent.reliability.llm_calls import ReliableModels

logger = logging.getLogger(__name__)
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "rewrite.md"


def reset_turn() -> dict[str, Any]:
    return {
        "rewritten_query": "",
        "output_guard_flag": None,
        "intent": None,
        "intent_confidence": 0,
        "path": None,
        "route_source": "whole",
        "parts": [],
        "part_retrievals": Overwrite([]),
        "intent_low_confidence": False,
        "classification_failed": False,
        "classification_error_type": None,
        "classifier_model": None,
        "answered_by_model": {},
        "reliability_events": [],
        "cache_events": [],
        "context_calls": [],
        "answer_cache_hit": None,
        "retrieval": [],
        "retrieval_build_id": None,
        "filters": None,
        "filters_applied": False,
        "gate": None,
        "retrieval_error_type": None,
        "retrieval_dependency_unavailable": False,
        "answer_status": "not_attempted",
        "answer_error_type": None,
        "coverage": None,
        "grounding_drafts": [],
        "claims": None,
        "claims_removed": 0,
        "order_context": None,
        "refund_candidates": [],
        "refund_order_id": None,
        "refund_policy_query": "",
        "refund_decision": None,
        "refund_request": None,
        "handoff": None,
        "tool_errors": 0,
        "consecutive_tool_errors": 0,
        "agent_steps": 0,
        "fallback_to_knowledge": False,
        "answer": "",
        "citations": [],
        "compaction_events": 0,
        "second_level_compactions": 0,
        "summariser_calls": 0,
    }


def make_rewrite_node(
    models: ReliableModels, settings: Settings
) -> Callable[[ConversationState], dict[str, Any]]:
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    def rewrite(state: ConversationState) -> dict[str, Any]:
        if not state.messages or not isinstance(state.messages[-1], HumanMessage):
            raise ValueError("A current human text message is required")
        original = state.messages[-1].content
        if not isinstance(original, str) or not original.strip():
            raise ValueError("A current human text message is required")
        query = original
        human_indices = [
            index
            for index, message in enumerate(state.messages)
            if isinstance(message, HumanMessage)
        ]
        turn_number = max(1, len(human_indices))
        st_cfg = settings.memory.short_term
        facts = state.pinned_facts
        blocks = list(state.compacted_blocks)
        history_start = state.history_start_index
        compaction_events = 0
        second_level = 0
        summariser_calls = 0

        if st_cfg.enabled:
            if st_cfg.pinned_facts_enabled:
                facts = extract_facts_from_turn(
                    original,
                    turn_number,
                    facts,
                    models=models,
                    use_llm=st_cfg.llm_fact_extraction,
                )
            if (
                st_cfg.compaction_enabled
                and settings.context.strategy != "sliding"
                and len(state.messages) > 1
            ):
                effective_st = (
                    st_cfg.model_copy(update={"strategy": "rolling"})
                    if settings.context.strategy == "rolling"
                    else st_cfg.model_copy(update={"strategy": "chunked"})
                )
                comp = compact_history(
                    state.messages[:-1],
                    active_history_start=history_start,
                    existing_blocks=blocks,
                    current_turn=turn_number,
                    settings=effective_st,
                    models=models,
                    builder=models.context_builder(),
                )
                blocks = comp.blocks
                history_start = comp.active_history_start
                compaction_events = comp.compacted_chunks
                second_level = comp.second_level_merges
                summariser_calls = comp.summariser_calls

        if len(human_indices) > 1:
            try:
                built = models.context_builder().build(
                    "rewrite",
                    task_prompt=prompt,
                    user_text=original,
                    history=state.messages[history_start:-1],
                    compacted_blocks=[b.text for b in blocks],
                    pinned_facts=facts.render_dict() or None if st_cfg.enabled else None,
                )
                response, _ = models.invoke("rewrite", "fast", built)
                if not isinstance(response.content, str) or not response.content.strip():
                    raise ValueError("Rewrite must be nonempty text")
                query = response.content.strip()
            except Exception as error:
                logger.warning("Query rewrite failed: %s", type(error).__name__)
        return {
            "rewritten_query": query,
            "pinned_facts": facts,
            "compacted_blocks": blocks,
            "history_start_index": history_start,
            "compaction_events": compaction_events,
            "second_level_compactions": second_level,
            "summariser_calls": summariser_calls,
            "trace": [*state.trace, "rewrite"],
        }

    return rewrite
