"""Retrieve, gate, and answer knowledge questions with source citations."""

from __future__ import annotations

import logging
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from support_agent.gate.evidence import evaluate
from support_agent.graph.coverage import CoverageAnswer, render_covered_answer
from support_agent.graph.deps import GraphDeps
from support_agent.graph.handoff import PROMPTS, HandoffReason, make_handoff
from support_agent.graph.state import CitationRecord, ConversationState
from support_agent.retrieval.scope import scope_chunks
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
        error_type = None
        retrieval = self.deps.settings.retrieval
        scope = retrieval.store_scope
        pool = (
            max(retrieval.rerank_top_k, scope.pool_k) if scope.enabled else retrieval.rerank_top_k
        )
        try:
            ranked = self.deps.knowledge_retriever().retrieve(state.rewritten_query, pool)
            chunks, store, dropped = scope_chunks(
                state.rewritten_query, ranked, scope, retrieval.rerank_top_k
            )
            if dropped:
                logger.info("Store scope %s dropped %d other-store chunks", store, dropped)
        except Exception as error:
            error_type = type(error).__name__
            logger.warning("Knowledge retrieval failed: %s", error_type)
            chunks = []
        return {
            "retrieval": chunks,
            "retrieval_error_type": error_type,
            "trace": [*state.trace, "retrieve"],
        }

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
        reason = (
            HandoffReason.RETRIEVAL_ERROR
            if state.retrieval_error_type
            else HandoffReason.LOW_EVIDENCE
        )
        return {**make_handoff(current, reason), "trace": current.trace}

    def answer(self, state: ConversationState) -> dict[str, Any]:
        if state.gate is None or not state.gate.passed:
            return self.handoff(state)
        chunks = state.retrieval[: self.deps.settings.retrieval.rerank_top_k]
        sources = self._sources(chunks)
        try:
            model = self.deps.model("main").with_structured_output(CoverageAnswer, include_raw=True)
            response = model.invoke(
                [
                    SystemMessage(content=self.prompt),
                    HumanMessage(
                        content=f"Question:\n{state.rewritten_query}\n\nSources:\n{sources}"
                    ),
                ]
            )
        except Exception as error:
            logger.warning("Knowledge answer failed: %s", type(error).__name__)
            return {
                **self._answer_handoff(state, "model_error"),
                "answer_error_type": type(error).__name__,
            }
        try:
            if not isinstance(response, dict) or response.get("parsing_error"):
                raise ValueError("Invalid structured answer envelope")
            coverage = CoverageAnswer.model_validate(response.get("parsed"))
        except Exception as error:
            return {
                **self._answer_handoff(state, "invalid_output"),
                "answer_error_type": type(error).__name__,
            }
        status, text = render_covered_answer(coverage, chunks)
        if status != "answered":
            current = state.model_copy(update={"coverage": coverage})
            return {**self._answer_handoff(current, status), "coverage": coverage}
        cleaned, citations = self._check_citations(text, chunks)
        return {
            "answer": cleaned,
            "messages": [AIMessage(content=cleaned)],
            "citations": [item.model_dump() for item in citations],
            "trace": [*state.trace, "answer"],
            "answer_status": "answered",
            "coverage": coverage,
        }

    def _answer_handoff(self, state: ConversationState, status: str) -> dict[str, Any]:
        current = state.model_copy(deep=True)
        current.trace.append("handoff")
        return {
            **make_handoff(
                current,
                HandoffReason.ANSWER_ERROR
                if status == "model_error"
                else HandoffReason.INCOMPLETE_EVIDENCE
                if status in {"insufficient_coverage", "implied_by_absence"}
                else HandoffReason.INVALID_ANSWER,
            ),
            "trace": current.trace,
            "citations": [],
            "answer_status": status,
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
