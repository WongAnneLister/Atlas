from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableLambda

from support_agent.config import Settings
from support_agent.graph.build import build_graph
from support_agent.graph.deps import GraphDeps
from support_agent.graph.intents import Intent
from support_agent.graph.nodes.knowledge import KnowledgePath
from support_agent.graph.state import ConversationState
from support_agent.retrieval.filters import RetrievalFilters
from support_agent.retrieval.types import RetrievedChunk


class FixedRetriever:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self.chunks = chunks
        self.calls: list[tuple[str, int]] = []

    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        self.calls.append((query, top_k))
        return self.chunks[:top_k]


class BrokenRetriever:
    def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        raise ConnectionError("private backend detail")


class FilterRecordingRetriever:
    def __init__(self, supported: bool = True) -> None:
        self.supported = supported
        self.calls: list[RetrievalFilters | None] = []

    def supports_filters(self) -> bool:
        return self.supported

    def retrieve(
        self, query: str, top_k: int, filters: RetrievalFilters | None = None
    ) -> list[RetrievedChunk]:
        self.calls.append(filters)
        return []


def evidence(score: float) -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            chunk_id="chunk-1",
            doc_id="policy",
            section_id="returns.window",
            title="Returns",
            heading_path="Returns > Window",
            text="Items can be returned within 30 days.",
            n_tokens=8,
            scores={"rerank": score},
        )
    ]


def fast_model() -> FakeListChatModel:
    from test_graph import StructuredFake

    return StructuredFake(
        responses=["unused"],
        predictions=[{"intent": Intent.POLICY_QUESTION, "confidence": 0.99}],
    )


def invoke(graph: Any, question: str) -> dict[str, Any]:
    return graph.invoke(
        {"messages": [HumanMessage(content=question)]},
        {"configurable": {"thread_id": "knowledge-test"}},
    )


def test_high_evidence_answers_with_valid_source_metadata() -> None:
    settings = Settings()
    settings.gate.threshold = 0.7
    main = CoverageFake(
        responses=["unused"], payload={"parts": [part("You have 30 days to return the item.")]}
    )
    retriever = FixedRetriever(evidence(0.99))
    with GraphDeps(
        settings,
        fast_model=fast_model(),
        main_model=main,
        retriever=retriever,
    ) as deps:
        result = invoke(build_graph(deps), "How long do I have to return an item?")
    assert result["trace"] == [
        "input_guard",
        "rewrite",
        "classify",
        "retrieve",
        "gate",
        "answer",
        "output_guard",
    ], result["gate"]
    assert result["answer"] == "You have 30 days to return the item. [1]"
    assert result["citations"] == [
        {
            "n": 1,
            "chunk_id": "chunk-1",
            "section_id": "returns.window",
            "heading_path": "Returns > Window",
        }
    ]
    assert retriever.calls == [
        ("How long do I have to return an item?", settings.retrieval.store_scope.pool_k)
    ]


def test_low_evidence_hands_off_without_calling_answer_model() -> None:
    settings = Settings()
    settings.gate.threshold = 0.8
    main = FakeListChatModel(responses=["This must never be called"])
    with GraphDeps(
        settings,
        fast_model=fast_model(),
        main_model=main,
        retriever=FixedRetriever(evidence(0.01)),
    ) as deps:
        result = invoke(build_graph(deps), "Can I pay with gold bars?")
    assert result["trace"] == [
        "input_guard",
        "rewrite",
        "classify",
        "retrieve",
        "gate",
        "handoff",
        "output_guard",
    ]
    assert result["handoff"].reason == "low_evidence"
    assert result["handoff"].retrieval_snapshot[0].chunk_id == "chunk-1"
    assert result["handoff"].gate.signals["top_score"] == 0.01
    assert main.responses == ["This must never be called"]


@pytest.mark.parametrize(
    ("question", "category"),
    [
        ("I bought it in August. Can I return a hair dryer?", "hair_dryers"),
        ("Can I return a hair dryer and headphones?", None),
    ],
)
def test_empty_filtered_retrieval_hands_off_without_retry(
    question: str, category: str | None
) -> None:
    settings = Settings()
    retriever = FilterRecordingRetriever()
    main = CoverageFake(responses=["unused"], payload={"parts": [part()]})
    with GraphDeps(settings, fast_model=fast_model(), main_model=main, retriever=retriever) as deps:
        result = invoke(build_graph(deps), question)
    assert result["trace"] == [
        "input_guard",
        "rewrite",
        "classify",
        "retrieve",
        "gate",
        "handoff",
        "output_guard",
    ]
    assert main.calls == 0
    assert result["gate"].reason == "empty_retrieval"
    assert result["handoff"].reason == "low_evidence"
    assert len(retriever.calls) == 1
    filters = retriever.calls[0]
    assert filters is not None
    assert filters.as_of == settings.orders.today
    assert filters.product_category == category
    assert result["filters"] == result["handoff"].filters == filters
    assert result["filters_applied"] is result["handoff"].filters_applied is True


def test_disabled_retrieval_filters_make_one_unfiltered_search() -> None:
    settings = Settings()
    settings.retrieval.filters.enabled = False
    retriever = FilterRecordingRetriever()
    with GraphDeps(settings, fast_model=fast_model(), retriever=retriever) as deps:
        result = invoke(build_graph(deps), "Can I return an item?")
    assert result["trace"][-4:] == ["retrieve", "gate", "handoff", "output_guard"]
    assert retriever.calls == [None]
    assert result["filters"] is result["handoff"].filters is None
    assert result["filters_applied"] is result["handoff"].filters_applied is False


def test_legacy_retrieval_records_requested_filters_without_applying_them() -> None:
    settings = Settings()
    retriever = FilterRecordingRetriever(supported=False)
    with GraphDeps(settings, fast_model=fast_model(), retriever=retriever) as deps:
        result = invoke(build_graph(deps), "Can I return an item?")
    assert result["trace"][-4:] == ["retrieve", "gate", "handoff", "output_guard"]
    assert retriever.calls == [None]
    assert result["filters"].as_of == settings.orders.today
    assert result["handoff"].filters == result["filters"]
    assert result["filters_applied"] is result["handoff"].filters_applied is False


def test_retrieval_failure_fails_closed_to_handoff(caplog: Any) -> None:
    settings = Settings()
    settings.gate.threshold = 0.8
    main = FakeListChatModel(responses=["This must never be called"])
    with GraphDeps(
        settings,
        fast_model=fast_model(),
        main_model=main,
        retriever=BrokenRetriever(),
    ) as deps:
        result = invoke(build_graph(deps), "Can I return a gold bar?")
    assert result["trace"] == [
        "input_guard",
        "rewrite",
        "classify",
        "retrieve",
        "gate",
        "handoff",
        "output_guard",
    ]
    assert result["gate"].reason == "empty_retrieval"
    assert result["handoff"].reason == "dependency_unavailable"
    assert main.responses == ["This must never be called"]
    assert "private backend detail" not in caplog.text


def test_retrieval_error_is_distinct_from_missing_evidence() -> None:
    settings = Settings()
    with GraphDeps(settings, fast_model=fast_model(), retriever=BrokenRetriever()) as deps:
        result = invoke(build_graph(deps), "Explain the return rules.")
    assert result["trace"] == [
        "input_guard",
        "rewrite",
        "classify",
        "retrieve",
        "gate",
        "handoff",
        "output_guard",
    ]
    assert result["retrieval_error_type"] == "ConnectionError"
    assert result["handoff"].reason == "dependency_unavailable"


def test_generation_connection_error_does_not_claim_low_evidence(caplog: Any) -> None:
    class BrokenModel(FakeListChatModel):
        def invoke(self, *args: Any, **kwargs: Any) -> Any:
            raise ConnectionError("private provider detail")

        def with_structured_output(self, *args: Any, **kwargs: Any) -> Any:
            return RunnableLambda(self.invoke)

    settings = Settings()
    settings.gate.threshold = 0.7
    with GraphDeps(
        settings,
        fast_model=fast_model(),
        main_model=BrokenModel(responses=["unused"]),
        retriever=FixedRetriever(evidence(0.99)),
    ) as deps:
        result = invoke(build_graph(deps), "Explain the return rules.")
    assert result["gate"].passed
    assert result["trace"] == [
        "input_guard",
        "rewrite",
        "classify",
        "retrieve",
        "gate",
        "handoff",
        "output_guard",
    ]
    assert result["answer_status"] == "model_error"
    assert result["answer_error_type"] == "ConnectionError"
    assert result["handoff"].reason == "dependency_unavailable"
    assert "private provider detail" not in caplog.text


class CoverageFake(FakeListChatModel):
    payload: dict[str, Any]
    calls: int = 0

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        self.calls += 1
        return RunnableLambda(
            lambda messages: {
                "parsed": self.payload,
                "raw": None,
                "parsing_error": None,
            }
        )


def part(answer: str = "Unused items can be returned within 30 days.", **changes: Any) -> dict:
    return {
        "question": "What is the return window?",
        "supported": True,
        "explicit": True,
        "answer": answer,
        "evidence": [{"source": 1, "quote": "Items can be returned within 30 days."}],
        **changes,
    }


def coverage_graph(payload: dict) -> dict:
    settings = Settings()
    settings.gate.threshold = 0.7
    with GraphDeps(
        settings,
        fast_model=fast_model(),
        main_model=CoverageFake(responses=["unused"], payload=payload),
        retriever=FixedRetriever(evidence(0.99)),
    ) as deps:
        return invoke(build_graph(deps), "What is the return window and refund processing time?")


def test_partial_coverage_creates_handoff_even_with_high_gate_score() -> None:
    result = coverage_graph(
        {
            "parts": [
                part(),
                {
                    "question": "How long does refund processing take?",
                    "supported": False,
                    "explicit": False,
                    "answer": "",
                    "evidence": [],
                },
            ]
        }
    )
    assert result["gate"].passed
    assert result["trace"] == [
        "input_guard",
        "rewrite",
        "classify",
        "retrieve",
        "gate",
        "handoff",
        "output_guard",
    ]
    assert result["handoff"].reason == "incomplete_evidence"
    assert result["answer_status"] == "insufficient_coverage"
    assert "30 days" not in result["answer"]
    assert result["citations"] == []
    assert result["coverage"].parts[1].supported is False
    assert result["handoff"].coverage.parts[1].question == "How long does refund processing take?"


@pytest.mark.parametrize(
    "citation",
    [
        {"source": 2, "quote": "Items can be returned within 30 days."},
        {"source": 1, "quote": "Refunds are processed instantly."},
        {"source": 1, "quote": ""},
    ],
)
def test_invalid_evidence_cannot_become_a_cited_answer(citation: dict) -> None:
    result = coverage_graph({"parts": [part(evidence=[citation])]})
    assert result["trace"][-2:] == ["handoff", "output_guard"]
    assert result["answer_status"] in {"invalid_output", "invalid_evidence"}
    assert result["citations"] == []


def test_supported_parts_get_code_generated_citations() -> None:
    result = coverage_graph({"parts": [part()]})
    assert result["trace"] == [
        "input_guard",
        "rewrite",
        "classify",
        "retrieve",
        "gate",
        "answer",
        "output_guard",
    ]
    assert result["answer"] == "Unused items can be returned within 30 days. [1]"
    assert result["citations"][0]["section_id"] == "returns.window"
    assert result["answer_status"] == "answered"


def test_direct_answer_without_passing_gate_never_invokes_model() -> None:
    path = KnowledgePath(GraphDeps(Settings(), main_model=FakeListChatModel(responses=["unused"])))
    result = path.answer(ConversationState(retrieval=evidence(0.99)))
    assert result["trace"] == ["handoff"]
    assert result["handoff"].reason == "low_evidence"


@pytest.mark.parametrize(
    "payload", [{"parts": []}, {"parts": [part(supported="true")]}, {"parts": [part(evidence=[])]}]
)
def test_malformed_or_evidenceless_decision_fails_closed(payload: dict) -> None:
    result = coverage_graph(payload)
    assert result["trace"][-2:] == ["handoff", "output_guard"]
    assert result["answer_status"] == "invalid_output"
    assert result["citations"] == []


def test_citation_renderer_removes_unknown_source_numbers() -> None:
    settings = Settings()
    settings.gate.threshold = 0.8
    path = KnowledgePath(
        GraphDeps(settings, main_model=FakeListChatModel(responses=["The window is 30 days [7]."]))
    )
    state = ConversationState(
        rewritten_query="return window",
        retrieval=evidence(0.99),
        trace=["retrieve", "gate"],
    )
    checked, citations = path._check_citations("The window is 30 days [1] [7].", state.retrieval)
    assert checked == "The window is 30 days [1]."
    assert [citation.n for citation in citations] == [1]
    no_citation, citations = path._check_citations("The window is 30 days [7].", state.retrieval)
    assert no_citation == "The window is 30 days."
    assert citations == []


def test_next_turn_clears_coverage_and_answer_failure_fields() -> None:
    from test_graph import fake

    settings = Settings()
    model = fake(Intent.POLICY_QUESTION, Intent.CHITCHAT_OTHER)
    with GraphDeps(
        settings,
        fast_model=model,
        main_model=CoverageFake(responses=["unused"], payload={"parts": [part()]}),
        retriever=FixedRetriever(evidence(0.99)),
    ) as deps:
        graph = build_graph(deps)
        first = invoke(graph, "What is the return window?")
        assert first["coverage"] is not None
        assert first["filters"] is not None
        graph.update_state(
            {"configurable": {"thread_id": "knowledge-test"}},
            {
                "answer_status": "model_error",
                "answer_error_type": "ConnectionError",
                "retrieval_error_type": "TimeoutError",
                "filters_applied": True,
            },
        )
        second = invoke(graph, "hello")
    assert second["coverage"] is None
    assert second["answer_status"] == "not_attempted"
    assert second["answer_error_type"] is None
    assert second["retrieval_error_type"] is None
    assert second["filters"] is None
    assert second["filters_applied"] is False


def store_chunk(chunk_id: str, section_id: str, text: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        doc_id="payments",
        section_id=section_id,
        title="Payments",
        heading_path="Payments",
        text=text,
        n_tokens=8,
        scores={"rerank": score},
    )


def test_single_store_question_never_sees_the_other_stores_policy() -> None:
    """Regression: a generic-store question was answered with Flipkart's COD limit."""
    settings = Settings()
    main = FakeListChatModel(responses=["This must never be called"])
    retriever = FixedRetriever(
        [
            store_chunk(
                "fk",
                "shipping.flipkart_faqs.payment.x",
                "You can shop up to Rs. 49,999 using Cash on Delivery.",
                0.99,
            ),
            store_chunk(
                "gen",
                "payments.maktek_faqs.generic-store.y",
                "We accept major credit cards, debit cards, and PayPal.",
                0.02,
            ),
        ]
    )
    with GraphDeps(settings, fast_model=fast_model(), main_model=main, retriever=retriever) as deps:
        result = invoke(
            build_graph(deps),
            "For the generic store: What is the maximum amount I can pay with Cash on Delivery?",
        )
    assert result["trace"] == [
        "input_guard",
        "rewrite",
        "classify",
        "retrieve",
        "gate",
        "handoff",
        "output_guard",
    ]
    assert [chunk.chunk_id for chunk in result["retrieval"]] == ["gen"]
    assert result["handoff"].reason == "low_evidence"
    assert main.responses == ["This must never be called"]


def test_answer_from_absence_hands_off_even_with_valid_quotes() -> None:
    no = "No, a cheque is not listed among the accepted methods."
    result = coverage_graph({"parts": [part(answer=no, explicit=False)]})
    assert result["trace"] == [
        "input_guard",
        "rewrite",
        "classify",
        "retrieve",
        "gate",
        "handoff",
        "output_guard",
    ]
    assert result["handoff"].reason == "incomplete_evidence"
    assert result["answer_status"] == "implied_by_absence"
    assert "cheque" not in result["answer"]
    assert result["citations"] == []


def test_coverage_part_requires_the_explicit_flag() -> None:
    payload = part()
    del payload["explicit"]
    result = coverage_graph({"parts": [payload]})
    assert result["answer_status"] == "invalid_output"


def test_bad_retrieval_result_keeps_retrieval_error_reason() -> None:
    class InvalidRetriever:
        def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
            raise ValueError("invalid data")

    with GraphDeps(Settings(), fast_model=fast_model(), retriever=InvalidRetriever()) as deps:
        result = invoke(build_graph(deps), "Explain the return rules.")
    assert result["trace"] == [
        "input_guard",
        "rewrite",
        "classify",
        "retrieve",
        "gate",
        "handoff",
        "output_guard",
    ]
    assert result["retrieval_error_type"] == "ValueError"
    assert result["handoff"].reason == "retrieval_error"
