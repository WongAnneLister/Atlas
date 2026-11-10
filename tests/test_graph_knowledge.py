from __future__ import annotations

from typing import Any

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import HumanMessage

from support_agent.config import Settings
from support_agent.graph.build import build_graph
from support_agent.graph.deps import GraphDeps
from support_agent.graph.intents import Intent
from support_agent.graph.nodes.knowledge import KnowledgePath
from support_agent.graph.state import ConversationState
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
    main = FakeListChatModel(responses=["You have 30 days to return the item [1]."])
    retriever = FixedRetriever(evidence(0.99))
    with GraphDeps(
        settings,
        fast_model=fast_model(),
        main_model=main,
        retriever=retriever,
    ) as deps:
        result = invoke(build_graph(deps), "How long do I have to return an item?")
    assert result["trace"] == ["rewrite", "classify", "retrieve", "gate", "answer"], result["gate"]
    assert result["answer"] == "You have 30 days to return the item [1]."
    assert result["citations"] == [
        {
            "n": 1,
            "chunk_id": "chunk-1",
            "section_id": "returns.window",
            "heading_path": "Returns > Window",
        }
    ]
    assert retriever.calls == [("How long do I have to return an item?", 5)]


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
    assert result["trace"] == ["rewrite", "classify", "retrieve", "gate", "handoff"]
    assert result["handoff"].reason == "low_evidence"
    assert result["handoff"].retrieval_snapshot[0].chunk_id == "chunk-1"
    assert result["handoff"].gate.signals["top_score"] == 0.01
    assert main.responses == ["This must never be called"]


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
    assert result["trace"] == ["rewrite", "classify", "retrieve", "gate", "handoff"]
    assert result["gate"].reason == "empty_retrieval"
    assert main.responses == ["This must never be called"]
    assert "private backend detail" not in caplog.text


def test_invalid_citation_is_removed_and_citationless_answer_hands_off() -> None:
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
    handoff = path.answer(state)
    assert handoff["trace"] == ["retrieve", "gate", "handoff"]
    assert handoff["handoff"].reason.value == "low_evidence"
