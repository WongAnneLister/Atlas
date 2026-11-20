"""A brief acknowledgement followed by an unconditional handoff."""

import logging
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from support_agent.graph.deps import GraphDeps
from support_agent.graph.handoff import PROMPTS, HandoffReason, load_templates, make_handoff
from support_agent.graph.state import ConversationState

logger = logging.getLogger(__name__)


class ComplaintPath:
    def __init__(self, deps: GraphDeps) -> None:
        self.deps = deps
        self.prompt = (PROMPTS / "complaint.md").read_text(encoding="utf-8")

    def __call__(self, state: ConversationState) -> dict[str, Any]:
        acknowledgement = load_templates("fixed_replies.yaml")["complaint_acknowledgement"]
        try:
            response, _ = self.deps.models.invoke(
                "complaint",
                "fast",
                [SystemMessage(content=self.prompt), HumanMessage(content=state.rewritten_query)],
            )
            text = response.content
            if isinstance(text, str) and text.strip():
                sentences = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
                # A conservative text check supplements the prompt; it is not a policy judge.
                forbidden = r"refund|compensat|replac|guarantee|promise|\d|[$£€]|\bwill\b"
                if len(
                    sentences
                ) <= self.deps.settings.agent.complaint_max_sentences and not re.search(
                    forbidden, text, flags=re.IGNORECASE
                ):
                    acknowledgement = text.strip()
        except Exception as error:
            logger.warning("Complaint acknowledgement failed: %s", type(error).__name__)
        current = state.model_copy(deep=True)
        current.trace.append("complaint")
        update = make_handoff(current, HandoffReason.COMPLAINT)
        answer = f"{acknowledgement} {update['answer']}"
        message = AIMessage(content=answer)
        update["handoff"].conversation = [*state.messages, message]
        return {**update, "answer": answer, "messages": [message], "trace": current.trace}
