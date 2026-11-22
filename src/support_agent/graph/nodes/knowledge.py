"""Retrieve, gate, and answer knowledge questions with source citations."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from support_agent.gate.evidence import evaluate
from support_agent.graph.coverage import (
    CoverageAnswer,
    CoverageStatus,
    render_covered_answer,
    render_covered_part,
)
from support_agent.graph.deps import GraphDeps
from support_agent.graph.handoff import (
    PROMPTS,
    HandoffReason,
    make_handoff,
    mark_parts_handed_off,
)
from support_agent.graph.intents import INTENT_TO_PATH, Path
from support_agent.graph.model_data import source_blocks
from support_agent.graph.parts import QueryPart
from support_agent.graph.state import CitationRecord, ConversationState
from support_agent.reliability.guards import diagnostic_type, is_dependency_failure
from support_agent.reliability.structured import StructuredOutputError
from support_agent.retrieval.filters import knowledge_filters, retrieve_with_filters
from support_agent.retrieval.scope import scope_chunks
from support_agent.retrieval.types import RetrievedChunk

logger = logging.getLogger(__name__)
_CITATION = re.compile(r"\[(\d+)\]")


def _part_sources(part: QueryPart, chunks: list[RetrievedChunk]) -> dict[int, RetrievedChunk]:
    local_ids = {chunk.chunk_id for chunk in part.retrieval}
    return {
        n: chunks[n - 1]
        for n in part.source_numbers
        if 1 <= n <= len(chunks) and chunks[n - 1].chunk_id in local_ids
    }


def _knowledge_part_passed(part: QueryPart) -> bool:
    return (
        part.intent is not None
        and INTENT_TO_PATH[part.intent] == Path.KNOWLEDGE
        and part.gate is not None
        and part.gate.passed
    )


def route_after_gate(state: ConversationState) -> str:
    if state.gate is None:
        raise ValueError("Knowledge path must evaluate the evidence gate before routing")
    return "answer" if state.gate.passed else "handoff"


class KnowledgePath:
    def __init__(self, deps: GraphDeps) -> None:
        self.deps = deps
        self.prompt = (PROMPTS / "answer.md").read_text(encoding="utf-8")
        self.parts_prompt = (PROMPTS / "answer_parts.md").read_text(encoding="utf-8")
        self.partial_handoff = (PROMPTS / "partial_handoff.txt").read_text(encoding="utf-8").strip()

    def retrieve(self, state: ConversationState) -> dict[str, Any]:
        error_type = None
        dependency_unavailable = False
        retrieval = self.deps.settings.retrieval
        filters = None
        filters_applied = False
        scope = retrieval.store_scope
        pool = (
            max(retrieval.rerank_top_k, scope.pool_k) if scope.enabled else retrieval.rerank_top_k
        )
        try:
            filters = knowledge_filters(state.rewritten_query, self.deps.settings)
            ranked, filters_applied = retrieve_with_filters(
                self.deps.knowledge_retriever(), state.rewritten_query, pool, filters
            )
            chunks, store, dropped = scope_chunks(
                state.rewritten_query, ranked, scope, retrieval.rerank_top_k
            )
            if dropped:
                logger.info("Store scope %s dropped %d other-store chunks", store, dropped)
        except Exception as error:
            error_type = diagnostic_type(error)
            dependency_unavailable = is_dependency_failure(error)
            logger.warning("Knowledge retrieval failed: %s", error_type)
            chunks = []
        return {
            "retrieval": chunks,
            "retrieval_build_id": self.deps.current_build_id(),
            "filters": filters,
            "filters_applied": filters_applied,
            "retrieval_error_type": error_type,
            "retrieval_dependency_unavailable": dependency_unavailable,
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
            HandoffReason.DEPENDENCY_UNAVAILABLE
            if state.retrieval_dependency_unavailable
            else HandoffReason.RETRIEVAL_ERROR
            if state.retrieval_error_type
            else HandoffReason.LOW_EVIDENCE
        )
        if state.route_source == "parts":
            current.parts = mark_parts_handed_off(state.parts, reason)
            return {**make_handoff(current, reason), "trace": current.trace, "parts": current.parts}
        return {**make_handoff(current, reason), "trace": current.trace}

    def answer(self, state: ConversationState) -> dict[str, Any]:
        if state.gate is None or not state.gate.passed:
            return self.handoff(state)
        if state.route_source == "parts":
            return self._answer_parts(state)
        chunks = state.retrieval[: self.deps.settings.retrieval.rerank_top_k]
        sources = source_blocks(chunks)
        coverage = self._request_coverage(
            state, self.prompt, f"Question:\n{state.rewritten_query}\n\nSources:\n{sources}"
        )
        if isinstance(coverage, dict):
            return coverage
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

    def _answer_parts(self, state: ConversationState) -> dict[str, Any]:
        candidates = {
            index: _part_sources(part, state.retrieval)
            for index, part in enumerate(state.parts)
            if _knowledge_part_passed(part)
        }
        if (
            state.retrieval_error_type
            or state.retrieval_dependency_unavailable
            or not candidates
            or (
                not self.deps.settings.knowledge.partial_answers
                and len(candidates) != len(state.parts)
            )
        ):
            return self.handoff(state)

        # The model sees no question or source belonging only to a failed part.
        data = [
            {
                "question": state.parts[index].text,
                "sources": [
                    {"number": n, "heading": chunk.heading_path, "text": chunk.text}
                    for n, chunk in sources.items()
                ],
            }
            for index, sources in candidates.items()
        ]
        coverage = self._request_coverage(
            state, self.parts_prompt, json.dumps(data, ensure_ascii=False)
        )
        if isinstance(coverage, dict):
            return coverage
        current = state.model_copy(update={"coverage": coverage})
        if [part.question for part in coverage.parts] != [
            state.parts[index].text.strip() for index in candidates
        ]:
            return self._answer_handoff(current, "invalid_output")
        return self._render_parts(current, candidates, coverage)

    def _render_parts(
        self,
        state: ConversationState,
        sources: dict[int, dict[int, RetrievedChunk]],
        coverage: CoverageAnswer,
    ) -> dict[str, Any]:
        parts = list(state.parts)
        paragraphs: list[str] = []
        failures: list[CoverageStatus] = []
        for (index, assigned), decision in zip(sources.items(), coverage.parts, strict=True):
            status, text, numbers = render_covered_part(decision, assigned)
            if status != "answered":
                failures.append(status)
                parts[index] = parts[index].model_copy(update={"failure_reason": status})
                continue
            paragraphs.append(text)
            parts[index] = parts[index].model_copy(
                update={
                    "answered": True,
                    "cited_section_ids": list(
                        dict.fromkeys(assigned[number].section_id for number in numbers)
                    ),
                }
            )

        current = state.model_copy(update={"parts": parts})
        if failures and (not paragraphs or not self.deps.settings.knowledge.partial_answers):
            return self._answer_handoff(current, failures[0])

        answer, citations = self._check_citations("\n\n".join(paragraphs), state.retrieval)
        handoff_data: dict[str, Any] = {}
        trace = [*state.trace, "answer"]
        if failed := [part for part in parts if not part.answered]:
            names = ", ".join(
                f"“{' '.join(_CITATION.sub('', part.text).split())}”" for part in failed
            )
            summary = self.partial_handoff.format(questions=names)
            remaining = iter(mark_parts_handed_off(failed, HandoffReason.UNSUPPORTED_PART))
            parts = [part if part.answered else next(remaining) for part in parts]
            current.parts = parts
            handoff_data = make_handoff(
                current, HandoffReason.UNSUPPORTED_PART, customer_message=summary
            )
            answer = f"{answer}\n\n{summary}"
            trace.append("handoff")
        return {
            **handoff_data,
            "answer": answer,
            "messages": [AIMessage(content=answer)],
            "citations": [item.model_dump() for item in citations],
            "trace": trace,
            "answer_status": "partial" if failed else "answered",
            "coverage": coverage,
            "parts": parts,
        }

    def _request_coverage(
        self, state: ConversationState, prompt: str, data: str
    ) -> CoverageAnswer | dict[str, Any]:
        try:
            response, _ = self.deps.models.structured(
                "answer",
                "main",
                CoverageAnswer,
                [
                    SystemMessage(content=prompt),
                    HumanMessage(content=data),
                ],
            )
        except StructuredOutputError as error:
            return {
                **self._answer_handoff(state, "invalid_output"),
                "answer_error_type": error.error_type,
            }
        except Exception as error:
            logger.warning("Knowledge answer failed: %s", type(error).__name__)
            return {
                **self._answer_handoff(
                    state, "model_error", dependency_unavailable=is_dependency_failure(error)
                ),
                "answer_error_type": type(error).__name__,
            }
        return response.value

    def _answer_handoff(
        self, state: ConversationState, status: str, *, dependency_unavailable: bool = False
    ) -> dict[str, Any]:
        current = state.model_copy(deep=True)
        current.trace.append("handoff")
        reason = (
            HandoffReason.DEPENDENCY_UNAVAILABLE
            if dependency_unavailable
            else HandoffReason.ANSWER_ERROR
            if status == "model_error"
            else HandoffReason.INCOMPLETE_EVIDENCE
            if status in {"insufficient_coverage", "implied_by_absence"}
            else HandoffReason.INVALID_ANSWER
        )
        parts_update: dict[str, Any] = {}
        if state.route_source == "parts":
            current.parts = mark_parts_handed_off(state.parts, status)
            parts_update["parts"] = current.parts
            parts_update["coverage"] = current.coverage
        return {
            **make_handoff(current, reason),
            **parts_update,
            "trace": current.trace,
            "citations": [],
            "answer_status": status,
        }

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
