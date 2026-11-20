"""Local fixed replies; this node never creates or invokes a language model."""

import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from support_agent.graph.handoff import load_templates
from support_agent.graph.state import ConversationState


def fixed_reply(state: ConversationState) -> dict[str, Any]:
    templates = load_templates("fixed_replies.yaml")
    original = next(
        (
            str(message.content)
            for message in reversed(state.messages)
            if isinstance(message, HumanMessage)
        ),
        state.rewritten_query,
    )
    category = "fallback"
    for name, pattern in (
        ("goodbye", r"\b(bye|goodbye|see you)\b"),
        ("thanks", r"\b(thanks|thank you|thx)\b"),
        ("capabilities", r"\b(what can you do|how can you help|capabilities)\b"),
        ("greeting", r"^\s*(hi|hello|hey|good morning|good evening)[\s!.,?]*$"),
    ):
        if re.search(pattern, original, flags=re.IGNORECASE):
            category = name
            break
    answer = templates["classification_failed" if state.classification_failed else category]
    return {
        "answer": answer,
        "messages": [AIMessage(content=answer)],
        "trace": [*state.trace, "fixed"],
    }
