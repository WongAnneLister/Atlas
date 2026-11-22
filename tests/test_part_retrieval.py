"""Offline coverage for retrieval fan-out, source numbering, and gate routing."""

import pytest

from support_agent.config import Settings
from support_agent.graph.deps import GraphDeps
from support_agent.graph.intents import Intent
from support_agent.graph.nodes.part_retrieval import (
    PartKnowledgeRetrieval,
    route_after_parts_gate,
)
from support_agent.graph.parts import PartRetrievalRequest, PartRetrievalResult, QueryPart
from support_agent.graph.state import ConversationState
from support_agent.reliability.events import ReliabilityEvent, record_event
from support_agent.retrieval.filters import RetrievalFilters
from support_agent.retrieval.types import RetrievedChunk


def chunk(chunk_id: str, section_id: str, score: float = 0.99) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        doc_id="policy",
        section_id=section_id,
        title="Returns",
        heading_path="Returns",
        text="Items can be returned within 30 days.",
        n_tokens=8,
        scores={"rerank": score},
    )


class RecordingRetriever:
    def __init__(self, results: dict[str, list[RetrievedChunk] | Exception]) -> None:
        self.results = results
        self.calls: list[tuple[str, int, RetrievalFilters | None]] = []

    def supports_filters(self) -> bool:
        return True

    def retrieve(
        self, query: str, top_k: int, filters: RetrievalFilters | None = None
    ) -> list[RetrievedChunk]:
        self.calls.append((query, top_k, filters))
        record_event(ReliabilityEvent(call_site=query, dependency="milvus", attempts=1))
        result = self.results[query]
        if isinstance(result, Exception):
            raise result
        return result[:top_k]


def test_parts_use_the_whole_store_scope_and_local_category() -> None:
    settings = Settings()
    filters = settings.retrieval.filters
    filters.enabled = filters.category = True
    settings.retrieval.store_scope.enabled = True
    parts = ["Can I return a hair dryer?", "How about headphones?"]
    question = f"For Flipkart, {' '.join(parts)}"
    matching = chunk("fk", "returns.flipkart_faqs.window")
    other_store = chunk("generic", "returns.maktek_faqs.window")
    retriever = RecordingRetriever({part: [other_store, matching] for part in parts})

    with GraphDeps(settings, retriever=retriever) as deps:
        path = PartKnowledgeRetrieval(deps)
        outputs = [
            path.retrieve_part(
                PartRetrievalRequest(index=index, text=part, rewritten_query=question)
            )["part_retrievals"][0]
            for index, part in enumerate(parts)
        ]

    assert retriever.calls == [
        (
            part,
            settings.retrieval.store_scope.pool_k,
            RetrievalFilters(as_of=settings.orders.today, product_category=category),
        )
        for part, category in zip(parts, ["hair_dryers", "headphones"], strict=True)
    ]
    assert [result.retrieval for result in outputs] == [[matching], [matching]]
    assert all(result.filters_applied for result in outputs)
    assert [result.reliability_events[0].call_site for result in outputs] == parts


def make_state(texts: list[str]) -> ConversationState:
    return ConversationState(
        rewritten_query=" ".join(texts),
        parts=[QueryPart(text=text, intent=Intent.POLICY_QUESTION) for text in texts],
        trace=["classify"],
    )


def test_merge_dedupes_by_planned_order_but_keeps_local_rerank_scores() -> None:
    state = make_state(["What is the return window?", "Who pays for return shipping?"])
    shared = chunk("shared", "returns.window")
    first = chunk("first", "returns.refund", 0.85)
    shared_weak = shared.model_copy(update={"scores": {"rerank": 0.02}})
    last = chunk("last", "returns.shipping", 0.01)
    retriever = RecordingRetriever(
        {state.parts[0].text: [shared, first], state.parts[1].text: [shared_weak, last]}
    )
    settings = Settings()
    settings.gate.threshold = 0.5
    settings.knowledge.partial_answers = True
    with GraphDeps(settings, retriever=retriever) as deps:
        path = PartKnowledgeRetrieval(deps)
        for index in (1, 0):
            state.part_retrievals.extend(
                path.retrieve_part(
                    PartRetrievalRequest(
                        index=index,
                        text=state.parts[index].text,
                        rewritten_query=state.rewritten_query,
                    )
                )["part_retrievals"]
            )
        merged = state.model_copy(update=path.merge(state))
        gated = merged.model_copy(update=path.gate_parts(merged))

    assert [item.chunk_id for item in gated.retrieval] == ["shared", "first", "last"]
    assert [part.source_numbers for part in gated.parts] == [[1, 2], [1, 3]]
    assert [item.call_site for item in gated.reliability_events] == [p.text for p in state.parts]
    first_gate, second_gate = (part.gate for part in gated.parts)
    assert first_gate is not None and first_gate.passed
    assert second_gate is not None and not second_gate.passed
    assert second_gate.signals["top_score"] == 0.02
    assert route_after_parts_gate(gated) == "answer"
    assert gated.trace == ["classify", "retrieve_part", "merge", "gate_parts"]


@pytest.mark.parametrize(
    ("error", "partial_answers", "reason", "error_type", "unavailable"),
    [
        (
            ConnectionError("private detail"),
            True,
            "dependency_unavailable",
            "ConnectionError",
            True,
        ),
        (ValueError("private detail"), True, "retrieval_error", "ValueError", False),
        (None, False, "empty_retrieval", None, False),
    ],
)
def test_route_handoff_when_retrieval_fails_or_partial_answers_are_disabled(
    error: Exception | None,
    partial_answers: bool,
    reason: str,
    error_type: str | None,
    unavailable: bool,
) -> None:
    state = make_state(["What is the return window?", "Can I pay in gold?"])
    retriever = RecordingRetriever(
        {state.parts[0].text: [chunk("good", "returns.window")], state.parts[1].text: error or []}
    )
    settings = Settings()
    settings.gate.threshold = 0.5
    settings.knowledge.partial_answers = partial_answers
    with GraphDeps(settings, retriever=retriever) as deps:
        path = PartKnowledgeRetrieval(deps)
        for index, part in enumerate(state.parts):
            state.part_retrievals.extend(
                path.retrieve_part(
                    PartRetrievalRequest(
                        index=index, text=part.text, rewritten_query=state.rewritten_query
                    )
                )["part_retrievals"]
            )
        merged = state.model_copy(update=path.merge(state))
        gated = merged.model_copy(update=path.gate_parts(merged))

    assert gated.parts[0].gate is not None and gated.parts[0].gate.passed
    assert gated.gate is not None and not gated.gate.passed and gated.gate.reason == reason
    assert gated.retrieval_error_type == error_type
    assert gated.retrieval_dependency_unavailable is unavailable
    assert route_after_parts_gate(gated) == "handoff"


@pytest.mark.parametrize(
    ("inconsistent_build", "inconsistent_chunk"),
    [(True, False), (False, True)],
)
def test_merge_fails_closed_when_branches_disagree_on_evidence(
    inconsistent_build: bool, inconsistent_chunk: bool
) -> None:
    state = make_state(["What is the return window?", "Who pays for return shipping?"])
    evidence = chunk("shared", "returns.window")
    conflicting = evidence.model_copy(update={"text": "Items are never returnable."})
    state.part_retrievals = [
        PartRetrievalResult(index=0, retrieval=[evidence], retrieval_build_id="known"),
        PartRetrievalResult(
            index=1,
            retrieval=[conflicting if inconsistent_chunk else evidence],
            retrieval_build_id="other" if inconsistent_build else "known",
        ),
    ]
    settings = Settings()
    settings.gate.threshold = 0.5
    settings.knowledge.partial_answers = True
    with GraphDeps(settings, retriever=RecordingRetriever({})) as deps:
        path = PartKnowledgeRetrieval(deps)
        merged = state.model_copy(update=path.merge(state))
        gated = merged.model_copy(update=path.gate_parts(merged))

    assert gated.retrieval_error_type == "ConflictingPartEvidence"
    assert gated.gate is not None and not gated.gate.passed
    assert route_after_parts_gate(gated) == "handoff"
