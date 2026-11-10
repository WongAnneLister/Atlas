"""Offline graph routes, rewriting, fail-closed classification and checkpoint ownership."""

from __future__ import annotations

import sqlite3
from pathlib import Path as FilePath
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from pydantic import Field, ValidationError

from support_agent.config import Settings
from support_agent.graph.build import build_graph
from support_agent.graph.deps import GraphDeps
from support_agent.graph.handoff import HandoffReason, make_handoff
from support_agent.graph.intents import INTENT_TO_PATH, PATH_NODES, Intent, Path
from support_agent.graph.nodes.classify import Classifier, IntentPrediction
from support_agent.graph.state import ConversationState
from support_agent.llm import override_chat_model
from support_agent.retrieval.types import RetrievedChunk


class StructuredFake(FakeListChatModel):
    predictions: list[Any] = Field(default_factory=list)
    classified_messages: list[list[BaseMessage]] = Field(default_factory=list)
    rewritten_messages: list[list[BaseMessage]] = Field(default_factory=list)

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        assert schema is IntentPrediction
        assert kwargs == {"include_raw": True}

        def classify(messages: list[BaseMessage]) -> dict[str, Any]:
            self.classified_messages.append(messages)
            value = self.predictions.pop(0)
            if isinstance(value, Exception):
                raise value
            if isinstance(value, dict) and "raw" in value:
                return value
            return {
                "parsed": value,
                "raw": AIMessage(content="", response_metadata={"model_name": "fake-fast"}),
                "parsing_error": None,
            }

        return RunnableLambda(classify)

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> AIMessage:
        self.rewritten_messages.append(input)
        return super().invoke(input, config, **kwargs)


@pytest.fixture(autouse=True)
def offline_main_model() -> Any:
    with override_chat_model("main", FakeListChatModel(responses=["unused"])):
        yield


def fake(
    *intents: Intent, confidence: float = 0.9, rewrite: str = "resolved question"
) -> StructuredFake:
    return StructuredFake(
        responses=[rewrite],
        predictions=[{"intent": intent, "confidence": confidence} for intent in intents],
    )


def invoke(graph: Any, question: str, thread: str = "conversation", **state: Any) -> dict[str, Any]:
    return graph.invoke(
        {"messages": [HumanMessage(content=question)], "customer_id": "customer-a", **state},
        {"configurable": {"thread_id": thread}},
    )


@pytest.mark.parametrize("intent", list(Intent))
def test_all_intents_follow_fixed_routes_and_skip_first_rewrite(intent: Intent) -> None:
    model = fake(intent)
    with GraphDeps(settings=Settings(), fast_model=model) as deps:
        result = invoke(build_graph(deps), "A self-contained customer request")
    path = INTENT_TO_PATH[intent]
    assert result["trace"] == ["rewrite", "classify", PATH_NODES[path]]
    assert result["intent"] == intent
    assert result["path"] == path
    if path in {Path.KNOWLEDGE, Path.AFTER_SALES}:
        assert result["answer"] == f"[path {path.value} not implemented]"
    else:
        assert result["answer"].strip()
    assert result["messages"][-1].content == result["answer"]
    assert result["rewritten_query"] == "A self-contained customer request"
    assert len(model.rewritten_messages) == (1 if path == Path.COMPLAINT else 0)
    assert len(model.classified_messages) == 1
    assert result["classifier_model"] == "fake-fast"


def test_followup_rewrites_with_history_and_keeps_append_only_trace() -> None:
    model = fake(
        Intent.PRODUCT_QUESTION, Intent.PRODUCT_QUESTION, rewrite="Does W40 Pro have a timer?"
    )
    with GraphDeps(settings=Settings(), fast_model=model) as deps:
        graph = build_graph(deps)
        invoke(graph, "Does this model have a timer?")
        result = invoke(graph, "what about the W40 Pro?")
    assert result["rewritten_query"] == "Does W40 Pro have a timer?"
    assert result["trace"] == ["rewrite", "classify", "knowledge"] * 2
    history = model.rewritten_messages[0]
    assert [message.type for message in history] == ["system", "human", "ai", "human"]
    assert history[-1].content == "what about the W40 Pro?"


def test_rewrite_history_bounds_human_turns_with_following_assistant() -> None:
    settings = Settings()
    settings.intent.rewrite_history_turns = 2
    model = fake(Intent.POLICY_QUESTION)
    with GraphDeps(settings=settings, fast_model=model) as deps:
        messages = [
            HumanMessage(content="old question"),
            AIMessage(content="old answer"),
            HumanMessage(content="recent question"),
            AIMessage(content="recent answer"),
            HumanMessage(content="and this one?"),
        ]
        build_graph(deps).invoke({"messages": messages}, {"configurable": {"thread_id": "history"}})
    assert [message.content for message in model.rewritten_messages[0][1:]] == [
        "recent question",
        "recent answer",
        "and this one?",
    ]


@pytest.mark.parametrize(
    "prediction", [ValueError("private text"), {"intent": "unknown", "confidence": 1}]
)
def test_classifier_failures_route_to_fixed_without_logging_raw_text(
    prediction: Any, caplog: Any
) -> None:
    model = StructuredFake(responses=["unused"], predictions=[prediction])
    with GraphDeps(settings=Settings(), fast_model=model) as deps:
        result = invoke(build_graph(deps), "private question")
    assert result["trace"] == ["rewrite", "classify", "fixed"]
    assert result["intent"] == Intent.CHITCHAT_OTHER
    assert result["intent_confidence"] == 0
    assert result["classification_failed"] is True
    assert "private text" not in caplog.text
    assert "private question" not in caplog.text


@pytest.mark.parametrize("confidence", [-0.1, 1.1, float("nan"), float("inf")])
def test_invalid_confidence_fails_closed(confidence: float) -> None:
    model = fake(Intent.PRODUCT_QUESTION, confidence=confidence)
    outcome = Classifier(model, Settings()).classify("a question")
    assert outcome.intent == Intent.CHITCHAT_OTHER
    assert outcome.confidence == 0
    assert outcome.parse_failed


@pytest.mark.parametrize("intent", list(Intent))
def test_low_confidence_flags_only_knowledge_and_after_sales(intent: Intent) -> None:
    model = fake(intent, confidence=0.1)
    with GraphDeps(settings=Settings(), fast_model=model) as deps:
        result = invoke(build_graph(deps), "request")
    path = INTENT_TO_PATH[intent]
    assert result["intent_low_confidence"] == (path in {Path.KNOWLEDGE, Path.AFTER_SALES})
    assert result["trace"][-1] == PATH_NODES[path]


def test_checkpoints_isolate_threads() -> None:
    model = fake(Intent.ORDER_STATUS, Intent.ORDER_STATUS)
    with GraphDeps(settings=Settings(), fast_model=model) as deps:
        graph = build_graph(deps)
        invoke(graph, "first thread", thread="one")
        result = invoke(graph, "second thread", thread="two")
    assert result["trace"] == ["rewrite", "classify", "tools"]
    assert len(result["messages"]) == 2
    assert model.rewritten_messages == []


def test_rewrite_clears_prior_turn_fields() -> None:
    model = fake(Intent.ORDER_STATUS, Intent.CHITCHAT_OTHER)
    stale = {
        "retrieval": [
            RetrievedChunk(
                chunk_id="old",
                doc_id="old",
                section_id="old",
                title="old",
                heading_path="old",
                text="old evidence",
                n_tokens=2,
            )
        ],
        "gate": {"passed": True},
        "order_context": {"order_id": "old"},
        "handoff": make_handoff(ConversationState(), HandoffReason.USER_REQUESTED)["handoff"],
        "tool_errors": 5,
        "consecutive_tool_errors": 2,
        "agent_steps": 5,
        "answer": "old",
        "citations": ["old"],
        "intent_low_confidence": True,
        "classification_failed": True,
        "classification_error_type": "OldError",
        "classifier_model": "old-model",
    }
    with GraphDeps(settings=Settings(), fast_model=model) as deps:
        graph = build_graph(deps)
        invoke(graph, "previous request")
        graph.update_state({"configurable": {"thread_id": "conversation"}}, stale)
        result = invoke(graph, "hello")
    assert result["retrieval"] == []
    assert result["gate"] is None
    assert result["order_context"] is None
    assert result["handoff"] is None
    assert result["tool_errors"] == 0
    assert result["consecutive_tool_errors"] == 0
    assert result["agent_steps"] == 0
    assert result["citations"] == []
    assert not result["intent_low_confidence"]
    assert not result["classification_failed"]
    assert result["classification_error_type"] is None


def test_sqlite_checkpoint_persists_and_dependency_owner_closes(tmp_path: FilePath) -> None:
    pytest.importorskip("langgraph.checkpoint.sqlite")
    settings = Settings()
    settings.graph.checkpoint_backend = "sqlite"
    settings.graph.checkpoint_path = str(tmp_path / "checkpoints.sqlite")
    deps = GraphDeps(settings=settings, fast_model=fake(Intent.ORDER_STATUS))
    graph = build_graph(deps)
    invoke(graph, "my order")
    saver = graph.checkpointer
    deps.close()
    deps.close()
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        saver.conn.execute("SELECT 1")
    with GraphDeps(settings=settings, fast_model=fake(Intent.ORDER_STATUS)) as next_deps:
        next_graph = build_graph(next_deps)
        saved = next_graph.get_state({"configurable": {"thread_id": "conversation"}})
        assert saved.values["trace"] == ["rewrite", "classify", "tools"]
        assert saved.values["messages"][0].content == "my order"


@pytest.mark.parametrize(
    "messages", [[], [AIMessage(content="wrong role")], [HumanMessage(content=" ")]]
)
def test_rejects_missing_current_human_text(messages: list[BaseMessage]) -> None:
    with (
        GraphDeps(settings=Settings(), fast_model=fake(Intent.CHITCHAT_OTHER)) as deps,
        pytest.raises(ValueError, match=r"human|Human"),
    ):
        build_graph(deps).invoke({"messages": messages}, {"configurable": {"thread_id": "bad"}})


def test_state_is_a_validated_boundary() -> None:
    with pytest.raises(ValidationError):
        ConversationState(intent_confidence=float("nan"))


@pytest.mark.parametrize("parsing_error", [None, ValueError("private parser body")])
def test_structured_parser_envelope_failure_preserves_raw_model_identity(
    parsing_error: Exception | None, caplog: Any
) -> None:
    model = StructuredFake(
        responses=["unused"],
        predictions=[
            {
                "raw": AIMessage(
                    content="private raw body", response_metadata={"model": "reported-model"}
                ),
                "parsed": None,
                "parsing_error": parsing_error,
            }
        ],
    )
    outcome = Classifier(model, Settings()).classify("private question")
    assert outcome.parse_failed
    assert outcome.intent == Intent.CHITCHAT_OTHER
    assert outcome.confidence == 0
    assert outcome.model_name == "reported-model"
    assert "private" not in caplog.text


@pytest.mark.parametrize("rewrite", ["", "   "])
def test_empty_rewrite_falls_back_to_original(rewrite: str) -> None:
    model = fake(Intent.POLICY_QUESTION, Intent.POLICY_QUESTION, rewrite=rewrite)
    with GraphDeps(settings=Settings(), fast_model=model) as deps:
        graph = build_graph(deps)
        invoke(graph, "first question")
        result = invoke(graph, "and for this one?")
    assert result["rewritten_query"] == "and for this one?"


def test_rewrite_exception_falls_back_without_logging_customer_text(
    monkeypatch: pytest.MonkeyPatch, caplog: Any
) -> None:
    model = fake(Intent.POLICY_QUESTION, Intent.POLICY_QUESTION)

    def fail(*args: Any, **kwargs: Any) -> AIMessage:
        raise RuntimeError("private provider body")

    monkeypatch.setattr(StructuredFake, "invoke", fail)
    with GraphDeps(settings=Settings(), fast_model=model) as deps:
        graph = build_graph(deps)
        invoke(graph, "first question")
        result = invoke(graph, "private customer question")
    assert result["rewritten_query"] == "private customer question"
    assert "RuntimeError" in caplog.text
    assert "private" not in caplog.text


def test_dependency_owner_closes_when_context_exits_with_error(tmp_path: FilePath) -> None:
    pytest.importorskip("langgraph.checkpoint.sqlite")
    settings = Settings()
    settings.graph.checkpoint_backend = "sqlite"
    settings.graph.checkpoint_path = str(tmp_path / "exception.sqlite")
    with (
        pytest.raises(RuntimeError, match="application failure"),
        GraphDeps(settings=settings, fast_model=fake(Intent.ORDER_STATUS)) as deps,
    ):
        graph = build_graph(deps)
        invoke(graph, "my order")
        raise RuntimeError("application failure")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        graph.checkpointer.conn.execute("SELECT 1")
    with pytest.raises(RuntimeError, match="closed"):
        build_graph(deps)
