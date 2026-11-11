"""Resolve follow-up references while preserving the customer's original facts."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from support_agent.config import Settings
from support_agent.graph.state import ConversationState

logger = logging.getLogger(__name__)
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "rewrite.md"


def make_rewrite_node(
    model: BaseChatModel, settings: Settings
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
        if len(human_indices) > 1:
            start = human_indices[-settings.intent.rewrite_history_turns :][0]
            messages: list[BaseMessage] = [SystemMessage(content=prompt), *state.messages[start:]]
            try:
                response = model.invoke(messages)
                if not isinstance(response.content, str) or not response.content.strip():
                    raise ValueError("Rewrite must be nonempty text")
                query = response.content.strip()
            except Exception as error:
                logger.warning("Query rewrite failed: %s", type(error).__name__)
        return {
            "rewritten_query": query,
            "intent": None,
            "intent_confidence": 0,
            "path": None,
            "intent_low_confidence": False,
            "classification_failed": False,
            "classification_error_type": None,
            "classifier_model": None,
            "retrieval": [],
            "gate": None,
            "retrieval_error_type": None,
            "answer_status": "not_attempted",
            "answer_error_type": None,
            "coverage": None,
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
            "answer": "",
            "citations": [],
            "trace": [*state.trace, "rewrite"],
        }

    return rewrite
