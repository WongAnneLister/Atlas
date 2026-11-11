"""Frozen phase-one free-text answer behavior for paired coverage experiments only."""

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from support_agent.config import REPO_ROOT
from support_agent.graph.nodes.knowledge import KnowledgePath
from support_agent.graph.state import ConversationState


class LegacyKnowledgePath(KnowledgePath):
    """Preserve the 56cdc00 answer acceptance rule; diagnostics do not alter outcomes."""

    def __init__(self, deps: Any) -> None:
        super().__init__(deps)
        self.prompt = (REPO_ROOT / "eval/prompts/coverage_round2_before.md").read_text()

    def answer(self, state: ConversationState) -> dict[str, Any]:
        if state.gate is None or not state.gate.passed:
            return self.handoff(state)
        sources = self._sources(state.retrieval[: self.deps.settings.retrieval.rerank_top_k])
        try:
            response = self.deps.model("main").invoke(
                [
                    SystemMessage(content=self.prompt),
                    HumanMessage(
                        content=f"Question:\n{state.rewritten_query}\n\nSources:\n{sources}"
                    ),
                ]
            )
            text = response.content
            if not isinstance(text, str) or not text.strip():
                return self._answer_handoff(state, "invalid_output")
            cleaned, citations = self._check_citations(text.strip(), state.retrieval)
            if not citations:
                return self._answer_handoff(state, "invalid_citation")
            return {
                "answer": cleaned,
                "messages": [AIMessage(content=cleaned)],
                "citations": [c.model_dump() for c in citations],
                "trace": [*state.trace, "answer"],
                "answer_status": "answered",
            }
        except Exception as error:
            return {
                **self._answer_handoff(state, "model_error"),
                "answer_error_type": type(error).__name__,
            }
