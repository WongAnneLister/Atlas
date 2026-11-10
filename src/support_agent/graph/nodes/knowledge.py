"""Retrieve, gate, and answer knowledge questions with source citations."""

from __future__ import annotations

import logging
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from support_agent.gate.evidence import evaluate
from support_agent.graph.deps import GraphDeps
from support_agent.graph.handoff import PROMPTS, HandoffReason, make_handoff
from support_agent.graph.state import CitationRecord, ConversationState
from support_agent.retrieval.types import RetrievedChunk

logger = logging.getLogger(__name__)
_CITATION = re.compile(r"\[(\d+)\]")


def route_after_gate(state: ConversationState) -> str:
    if state.gate is None:
        raise ValueError("Knowledge path must evaluate the evidence gate before routing")
    return "answer" if state.gate.passed else "handoff"


class KnowledgePath:
    def __init__(self, deps: GraphDeps) -> None:
        self.deps = deps
        self.prompt = (PROMPTS / "answer.md").read_text(encoding="utf-8")

    def retrieve(self, state: ConversationState) -> dict[str, Any]:
        try:
            chunks = self.deps.knowledge_retriever().retrieve(
                state.rewritten_query, self.deps.settings.retrieval.rerank_top_k
            )
        except Exception as error:
            logger.warning("Knowledge retrieval failed: %s", type(error).__name__)
            chunks = []
        return {"retrieval": chunks, "trace": [*state.trace, "retrieve"]}

    def gate(self, state: ConversationState) -> dict[str, Any]:
        result = evaluate(
            state.rewritten_query,
            state.retrieval,
            self.deps.settings.gate,
            allow_untuned=self.deps.allow_untuned_gate,
        )
        return {"gate": result, "trace": [*state.trace, "gate"]}

    def handoff(self, state: ConversationState) -> dict[str, Any]:
        current = state.model_copy(deep=True)
        current.trace.append("handoff")
        return {**make_handoff(current, HandoffReason.LOW_EVIDENCE), "trace": current.trace}

    def answer(self, state: ConversationState) -> dict[str, Any]:
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
                return self._answer_handoff(state)
            cleaned, citations = self._check_citations(text.strip(), state.retrieval)
            if not citations:
                return self._answer_handoff(state)
            return {
                "answer": cleaned,
                "messages": [AIMessage(content=cleaned)],
                "citations": [item.model_dump() for item in citations],
                "trace": [*state.trace, "answer"],
            }
        except Exception as error:
            logger.warning("Knowledge answer failed: %s", type(error).__name__)
            return self._answer_handoff(state)

    def _answer_handoff(self, state: ConversationState) -> dict[str, Any]:
        current = state.model_copy(deep=True)
        current.trace.append("handoff")
        return {
            **make_handoff(current, HandoffReason.LOW_EVIDENCE),
            "trace": current.trace,
            "citations": [],
        }

    @staticmethod
    def _sources(chunks: list[RetrievedChunk]) -> str:
        return "\n\n".join(
            f"[{number}] {chunk.heading_path}\n{chunk.text}"
            for number, chunk in enumerate(chunks, start=1)
        )

    @staticmethod
    def _check_citations(
        answer: str, chunks: list[RetrievedChunk]
    ) -> tuple[str, list[CitationRecord]]:
        valid_numbers = set(range(1, len(chunks) + 1))
        seen: set[int] = set()

        def replace(match: re.Match[str]) -> str:
            number = int(match.group(1))
            if number not in valid_numbers:
                return ""
            seen.add(number)
            return match.group(0)

        cleaned = re.sub(r"\s+([,.!?;:])", r"\1", _CITATION.sub(replace, answer)).strip()
        citations = [
            CitationRecord(
                n=number,
                chunk_id=chunks[number - 1].chunk_id,
                section_id=chunks[number - 1].section_id,
                heading_path=chunks[number - 1].heading_path,
            )
            for number in sorted(seen)
        ]
        return cleaned, citations
