"""Exercise real graph edges using only local model and retrieval fakes."""

from datetime import date
from threading import Lock
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from support_agent.config import Settings
from support_agent.graph.build import build_graph
from support_agent.graph.deps import GraphDeps
from support_agent.graph.intents import PATH_NODES, Intent, Path
from support_agent.reliability.structured import ParsedResponse
from support_agent.retrieval.filters import RetrievalFilters
from support_agent.retrieval.types import RetrievedChunk

RETURNS = "What is the generic store return window?"
SHIPPING = "Who pays return shipping?"
UNKNOWN = "Can a unicorn deliver my parcel?"
ORDER = "Where is my order?"
QUESTION = f"{RETURNS} Also, {SHIPPING}"
MULTIPART_TRACE = [
    "input_guard",
    "rewrite",
    "plan",
    "classify",
    "retrieve_part",
    "merge",
    "gate_parts",
]


def chunk(
    key: str = "returns",
    text: str = "Returns are accepted within 30 days.",
    dataset: str = "maktek_faqs",
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=key,
        section_id=f"returns.{dataset}.{key}",
        doc_id="returns",
        title="Returns",
        heading_path="Returns",
        text=text,
        n_tokens=8,
        scores={"rerank": 0.99},
    )


class Retriever:
    def __init__(self, rows: dict[str, list[RetrievedChunk] | Exception]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, RetrievalFilters | None]] = []
        self.lock = Lock()

    def supports_filters(self) -> bool:
        return True

    def retrieve(
        self, query: str, top_k: int, filters: RetrievalFilters | None = None
    ) -> list[RetrievedChunk]:
        with self.lock:
            self.calls.append((query, filters))
        value = self.rows.get(query, [])
        if isinstance(value, Exception):
            raise value
        return value[:top_k]


def graph_result(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    question: str,
    parts: list[str],
    intents: dict[str, Intent | Exception],
    retriever: Retriever,
    *,
    answer: list[dict[str, Any]] | None = None,
    service: Any = None,
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    calls: list[tuple[str, str]] = []

    def structured(site, role, schema, messages, **kwargs):
        text = messages[-1].content
        calls.append((site, text))
        if site == "plan":
            value = {
                "is_multi_part": True,
                "parts": [{"text": part, "key_terms": [part.split()[0]]} for part in parts],
            }
        elif site == "classify":
            intent = intents[text]
            if isinstance(intent, Exception):
                raise intent
            value = {"intent": intent, "confidence": 0.98}
        else:
            assert site == "answer" and answer is not None
            value = {"parts": answer}
        return ParsedResponse(schema.model_validate(value), "fixture"), None

    def invoke(site, role, messages):
        assert site == "complaint"
        return AIMessage(content="That sounds frustrating."), None

    settings.gate.threshold = 0.3
    with GraphDeps(settings, retriever=retriever, order_service=service) as deps:
        monkeypatch.setattr(deps.models, "structured", structured)
        monkeypatch.setattr(deps.models, "invoke", invoke)
        graph = build_graph(deps)
        state = {"messages": [HumanMessage(content=question)]}
        if service is not None:
            state["customer_id"] = "CUST-0001"
        result = graph.invoke(state, {"configurable": {"thread_id": "multipart-graph"}})
    return result, calls


def supported(question: str, source: RetrievedChunk, number: int = 1) -> dict[str, Any]:
    return {
        "question": question,
        "supported": True,
        "explicit": True,
        "answer": source.text,
        "evidence": [{"source": number, "quote": source.text}],
    }


@pytest.mark.parametrize("second", [Intent.POLICY_QUESTION, Intent.CHITCHAT_OTHER])
def test_routes_both_parts_and_only_answers_the_supported_part(monkeypatch, second):
    other = SHIPPING if second == Intent.POLICY_QUESTION else UNKNOWN
    question = f"{RETURNS} Also, {other}"
    source = chunk()
    foreign = chunk("foreign", dataset="flipkart_faqs")
    retriever = Retriever({RETURNS: [source, foreign], other: [foreign]})
    result, calls = graph_result(
        monkeypatch,
        Settings(),
        question,
        [RETURNS, other],
        {RETURNS: Intent.POLICY_QUESTION, other: second},
        retriever,
        answer=[supported(RETURNS, source)],
    )
    assert result["trace"] == [*MULTIPART_TRACE, "answer", "handoff", "output_guard"]
    assert result["route_source"] == "parts"
    assert result["path"] == Path.KNOWLEDGE
    assert [part.intent for part in result["parts"]] == [Intent.POLICY_QUESTION, second]
    assert result["answer_status"] == "partial"
    assert result["citations"][0]["section_id"] == source.section_id
    assert result["parts"][0].answered
    handoff = result["handoff"]
    assert [part.text for part in handoff.parts] == [other]
    assert handoff.parts[0].failure_reason == (
        "unsupported_part" if second == Intent.CHITCHAT_OTHER else "low_evidence"
    )
    assert handoff.parts[0].retrieval == []
    if second == Intent.CHITCHAT_OTHER:
        assert handoff.reason == "unsupported_part"
    assert [text for site, text in calls if site == "classify"] == [RETURNS, other]
    (model_input,) = [text for site, text in calls if site == "answer"]
    assert other not in model_input and "foreign" not in model_input
    expected = {RETURNS} if second == Intent.CHITCHAT_OTHER else {RETURNS, other}
    assert {text for text, _ in retriever.calls} == expected
    assert all(
        filters == RetrievalFilters(as_of=date(2026, 11, 9)) for _, filters in retriever.calls
    )


@pytest.mark.parametrize("dependency_failure", [False, True])
def test_all_gates_fail_or_one_dependency_fails_without_answer_model(
    monkeypatch, dependency_failure
):
    rows = {RETURNS: [chunk()], SHIPPING: ConnectionError("fixture")} if dependency_failure else {}
    result, calls = graph_result(
        monkeypatch,
        Settings(),
        QUESTION,
        [RETURNS, SHIPPING],
        dict.fromkeys([RETURNS, SHIPPING], Intent.POLICY_QUESTION),
        Retriever(rows),
    )
    assert result["trace"] == [*MULTIPART_TRACE, "handoff", "output_guard"]
    assert result["handoff"].reason == (
        "dependency_unavailable" if dependency_failure else "low_evidence"
    )
    assert not any(site == "answer" for site, _ in calls)
    assert not result["citations"]


@pytest.mark.parametrize("second", [Intent.ORDER_STATUS, ValueError("parse failure")])
def test_operational_part_or_classification_error_falls_back_to_whole_query(monkeypatch, second):
    question = f"{RETURNS} Also, {ORDER}"
    retriever = Retriever({})
    result, calls = graph_result(
        monkeypatch,
        Settings(),
        question,
        [RETURNS, ORDER],
        {RETURNS: Intent.POLICY_QUESTION, ORDER: second, question: Intent.TALK_TO_HUMAN},
        retriever,
    )
    assert result["trace"] == [
        "input_guard",
        "rewrite",
        "plan",
        "classify",
        "tools",
        "output_guard",
    ]
    assert result["route_source"] == "whole"
    assert result["path"] == Path.TOOLS
    assert [text for site, text in calls if site == "classify"] == [RETURNS, ORDER, question]
    assert not retriever.calls


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("What is the points program?", "How can I track a parcel?"),
        ("How much can I return?", "Who pays the shipping fee?"),
        ("How long is the trial?", "What is the return window?"),
        ("Can I get a receipt?", "How do I pay an invoice?"),
        ("What is your warranty?", "Do you offer free shipping?"),
        ("Can I use a coupon?", "Are gift returns accepted?"),
    ],
)
def test_also_questions_take_the_knowledge_route(monkeypatch, first, second):
    question = f"{first} Also, {second}"
    result, calls = graph_result(
        monkeypatch,
        Settings(),
        question,
        [first, second],
        dict.fromkeys([first, second], Intent.POLICY_QUESTION),
        Retriever({}),
    )
    assert result["trace"] == [*MULTIPART_TRACE, "handoff", "output_guard"]
    assert result["route_source"] == "parts"
    assert result["path"] == Path.KNOWLEDGE
    assert [text for site, text in calls if site == "classify"] == [first, second]


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize(
    ("path", "intent"),
    [
        (Path.TOOLS, Intent.TALK_TO_HUMAN),
        (Path.KNOWLEDGE, Intent.POLICY_QUESTION),
        (Path.AFTER_SALES, Intent.REFUND_REQUEST),
        (Path.COMPLAINT, Intent.COMPLAINT),
        (Path.FIXED, Intent.CHITCHAT_OTHER),
    ],
)
def test_single_routes_and_disabled_planning_preserve_legacy_calls(
    monkeypatch, seeded, path, intent, enabled
):
    settings, service = seeded
    settings.planning.enabled = enabled
    query = "One question?" if enabled else QUESTION
    retriever = Retriever({})
    result, calls = graph_result(
        monkeypatch, settings, query, [], {query: intent}, retriever, service=service
    )
    expected = ["input_guard", "rewrite", "classify"]
    if path == Path.AFTER_SALES:
        assert result["__interrupt__"][0].value["type"] == "order_picker"
    elif path == Path.KNOWLEDGE:
        expected += ["retrieve", "gate", "handoff", "output_guard"]
        assert len(retriever.calls) == 1
    else:
        expected += [PATH_NODES[path], "output_guard"]
    assert result["trace"] == expected
    assert result["route_source"] == "whole"
    assert calls == [("classify", query)]


def test_partial_answers_disabled_keep_whole_handoff(monkeypatch):
    settings = Settings()
    settings.knowledge.partial_answers = False
    result, calls = graph_result(
        monkeypatch,
        settings,
        QUESTION,
        [RETURNS, SHIPPING],
        dict.fromkeys([RETURNS, SHIPPING], Intent.POLICY_QUESTION),
        Retriever({RETURNS: [chunk()]}),
    )
    assert result["trace"] == [*MULTIPART_TRACE, "handoff", "output_guard"]
    assert result["handoff"].reason == "low_evidence"
    assert all(not part.answered for part in result["parts"])
    assert not any(site == "answer" for site, _ in calls)
