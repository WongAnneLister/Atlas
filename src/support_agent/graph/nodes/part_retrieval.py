"""Retrieve and gate each knowledge part while preserving its own evidence."""

from __future__ import annotations

import logging
from typing import Any

from support_agent.gate.evidence import GateResult, evaluate
from support_agent.graph.deps import GraphDeps
from support_agent.graph.intents import INTENT_TO_PATH, Path
from support_agent.graph.nodes.knowledge import route_after_gate
from support_agent.graph.parts import PartRetrievalRequest, PartRetrievalResult
from support_agent.graph.state import ConversationState
from support_agent.reliability.events import collect_events
from support_agent.reliability.guards import diagnostic_type, is_dependency_failure
from support_agent.retrieval.filters import (
    RetrievalFilters,
    knowledge_filters,
    retrieve_with_filters,
)
from support_agent.retrieval.scope import scope_chunks
from support_agent.retrieval.types import RetrievedChunk

logger = logging.getLogger(__name__)
_RANKING_FIELDS = {"scores", "ranks"}


class PartKnowledgeRetrieval:
    def __init__(self, deps: GraphDeps) -> None:
        self.deps = deps

    def retrieve_part(self, request: PartRetrievalRequest) -> dict[str, list[PartRetrievalResult]]:
        result = PartRetrievalResult(index=request.index)
        settings = self.deps.settings
        retrieval = settings.retrieval
        scope = retrieval.store_scope
        pool = (
            max(retrieval.rerank_top_k, scope.pool_k) if scope.enabled else retrieval.rerank_top_k
        )

        with collect_events() as events:
            try:
                result.filters = knowledge_filters(
                    request.rewritten_query, settings, category_query=request.text
                )
                ranked, result.filters_applied = retrieve_with_filters(
                    self.deps.knowledge_retriever(), request.text, pool, result.filters
                )
                result.retrieval, store, dropped = scope_chunks(
                    request.rewritten_query, ranked, scope, retrieval.rerank_top_k
                )
                if dropped:
                    logger.info("Store scope %s dropped %d other-store chunks", store, dropped)
                result.retrieval_build_id = self.deps.current_build_id()
            except Exception as error:
                result.retrieval_error_type = diagnostic_type(error)
                result.retrieval_dependency_unavailable = is_dependency_failure(error)
                result.retrieval = []
                logger.warning("Knowledge part retrieval failed: %s", result.retrieval_error_type)
        result.reliability_events = events
        return {"part_retrievals": [result]}

    def merge(self, state: ConversationState) -> dict[str, Any]:
        # Parallel branch completion order is irrelevant to citation numbering and diagnostics.
        results = sorted(state.part_retrievals, key=lambda result: result.index)
        by_index = {result.index: result for result in results}
        expected = {
            index
            for index, part in enumerate(state.parts)
            if part.intent is not None and INTENT_TO_PATH[part.intent] == Path.KNOWLEDGE
        }
        invalid_results = len(by_index) != len(results) or set(by_index) != expected
        parts = list(state.parts)
        chunks: list[RetrievedChunk] = []
        numbers: dict[str, int] = {}
        build_ids = {result.retrieval_build_id for result in results if result.retrieval_build_id}
        conflicting_evidence = len(build_ids) > 1

        for index in sorted(expected.intersection(by_index)):
            result = by_index[index]
            source_numbers: list[int] = []
            for chunk in result.retrieval:
                number = numbers.get(chunk.chunk_id)
                if number is None:
                    chunks.append(chunk)
                    number = numbers[chunk.chunk_id] = len(chunks)
                elif chunks[number - 1].model_dump(exclude=_RANKING_FIELDS) != chunk.model_dump(
                    exclude=_RANKING_FIELDS
                ):
                    conflicting_evidence = True
                source_numbers.append(number)
            parts[index] = parts[index].model_copy(
                update={
                    "retrieval": result.retrieval,
                    "filters": result.filters,
                    "filters_applied": result.filters_applied,
                    "source_numbers": source_numbers,
                    "failure_reason": _retrieval_failure(result),
                }
            )

        dependency_error = next(
            (result for result in results if result.retrieval_dependency_unavailable), None
        )
        failed = dependency_error or next(
            (result for result in results if result.retrieval_error_type), None
        )
        error_type = failed.retrieval_error_type if failed else None
        if error_type is None:
            if invalid_results:
                error_type = "InvalidPartRetrievalResults"
            elif conflicting_evidence:
                error_type = "ConflictingPartEvidence"
        if invalid_results or conflicting_evidence:
            logger.warning("Knowledge part results could not be merged consistently")

        filters = _shared_filters(results)
        return {
            "parts": parts,
            "retrieval": chunks,
            "retrieval_build_id": next(iter(build_ids)) if len(build_ids) == 1 else None,
            "filters": filters,
            "filters_applied": filters is not None and all(r.filters_applied for r in results),
            "retrieval_error_type": error_type,
            "retrieval_dependency_unavailable": dependency_error is not None,
            "reliability_events": [
                *state.reliability_events,
                *(event for result in results for event in result.reliability_events),
            ],
            "trace": [*state.trace, "retrieve_part", "merge"],
        }

    def gate_parts(self, state: ConversationState) -> dict[str, Any]:
        settings = self.deps.settings
        parts = list(state.parts)
        passed: list[GateResult] = []
        failed: list[GateResult] = []

        for index, part in enumerate(parts):
            if part.intent is None or INTENT_TO_PATH[part.intent] != Path.KNOWLEDGE:
                continue
            gate = evaluate(
                part.text, part.retrieval, settings.gate, allow_untuned=self.deps.allow_untuned_gate
            )
            parts[index] = part.model_copy(
                update={
                    "gate": gate,
                    "failure_reason": part.failure_reason
                    or (None if gate.passed else "low_evidence"),
                }
            )
            (passed if gate.passed else failed).append(gate)

        if state.retrieval_error_type:
            summary = evaluate(
                state.rewritten_query, [], settings.gate, allow_untuned=self.deps.allow_untuned_gate
            ).model_copy(
                update={
                    "reason": (
                        "dependency_unavailable"
                        if state.retrieval_dependency_unavailable
                        else "retrieval_error"
                    )
                }
            )
        elif passed and (settings.knowledge.partial_answers or len(passed) == len(parts)):
            summary = min(passed, key=lambda gate: gate.score)
        elif failed:
            summary = min(failed, key=lambda gate: gate.score)
        else:
            summary = evaluate(
                state.rewritten_query, [], settings.gate, allow_untuned=self.deps.allow_untuned_gate
            ).model_copy(update={"reason": "unsupported_part"})

        return {"parts": parts, "gate": summary, "trace": [*state.trace, "gate_parts"]}


def _retrieval_failure(result: PartRetrievalResult) -> str | None:
    if result.retrieval_dependency_unavailable:
        return "dependency_unavailable"
    return "retrieval_error" if result.retrieval_error_type else None


def _shared_filters(results: list[PartRetrievalResult]) -> RetrievalFilters | None:
    if not results or any(result.filters is None for result in results):
        return None
    filters = [result.filters for result in results if result.filters is not None]
    dates = {part_filter.as_of for part_filter in filters}
    categories = {part_filter.product_category for part_filter in filters}
    return RetrievalFilters(
        as_of=next(iter(dates)) if len(dates) == 1 else None,
        product_category=next(iter(categories)) if len(categories) == 1 else None,
    )


def route_after_parts_gate(state: ConversationState) -> str:
    return route_after_gate(state)
