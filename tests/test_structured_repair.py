"""Structured repair is a single sanitized call and obeys the existing graph checks."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableLambda
from pydantic import Field

from support_agent.config import Settings
from support_agent.graph.build import build_graph
from support_agent.graph.deps import GraphDeps
from support_agent.graph.intents import Intent
from test_graph import StructuredFake, invoke
from test_graph_knowledge import CoverageFake, FixedRetriever, evidence, fast_model, part
from test_refund_flow import DecisionFake


class SequenceCoverage(CoverageFake):
    replies: list[object] = Field(default_factory=list)
    seen: list[list[BaseMessage]] = Field(default_factory=list)

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        def reply(messages: list[BaseMessage]) -> Any:
            self.seen.append(list(messages))
            value = self.replies.pop(0)
            if isinstance(value, Exception):
                raise value
            return {"parsed": value, "raw": None, "parsing_error": None}

        return RunnableLambda(reply)


@pytest.mark.parametrize("forged", [False, True])
def test_answer_repair_still_checks_citations_and_quotes(forged: bool) -> None:
    settings = Settings()
    settings.gate.threshold = 0.7
    reply = part(evidence=[{"source": 1, "quote": "forged quote"}]) if forged else part()
    model = SequenceCoverage(
        responses=["unused"], payload={}, replies=[{"parts": []}, {"parts": [reply]}]
    )
    with GraphDeps(
        settings,
        fast_model=fast_model(),
        main_model=model,
        retriever=FixedRetriever(evidence(0.99)),
    ) as deps:
        result = invoke(build_graph(deps), "What is the return window?")

    assert result["trace"] == [
        "rewrite",
        "classify",
        "retrieve",
        "gate",
        "handoff" if forged else "answer",
    ]
    assert result["gate"].passed
    assert result["answer_status"] == ("invalid_evidence" if forged else "answered")
    assert bool(result["citations"]) is not forged
    assert model.seen[1][:-1] == model.seen[0]
    event = result["reliability_events"][-1]
    assert event.repaired and event.attempts == 2 and event.retries == 0


@pytest.mark.parametrize("repair_result", [{"intent": "not-an-intent"}, TimeoutError("private")])
def test_classifier_repair_has_no_retry_fallback_or_private_validation_input(
    repair_result: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings()
    settings.llm.fallbacks.fast = ["must-not-be-used"]
    settings.reliability.repair_error_max_chars = 12
    model = StructuredFake(
        responses=["unused"],
        predictions=[
            {"intent": "private output", "confidence": 0.95},
            repair_result,
            {"intent": "policy_question"},
        ],
    )

    def unexpected_fallback(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Neither parser errors nor repair failures may trigger fallback")

    monkeypatch.setattr("support_agent.graph.deps.get_chat_model", unexpected_fallback)
    with GraphDeps(settings, fast_model=model) as deps:
        result = invoke(build_graph(deps), "May I return this?")

    assert result["trace"] == ["rewrite", "classify", "fixed"]
    assert result["classification_failed"]
    assert len(model.classified_messages) == 2
    assert model.classified_messages[1][:-1] == model.classified_messages[0]
    repair = str(model.classified_messages[1][-1].content)
    assert "private output" not in repair
    assert repair.split("Validation issue: ", 1)[1] == "intent: enum"
    [event] = result["reliability_events"]
    assert event.repaired and event.attempts == 2 and event.retries == 0
    assert not event.fell_back
    assert result["answered_by_model"] == {}


def test_classifier_can_use_a_repaired_prediction() -> None:
    model = StructuredFake(
        responses=["unused"],
        predictions=[None, {"intent": Intent.CHITCHAT_OTHER, "confidence": 0.9}],
    )
    with GraphDeps(Settings(), fast_model=model) as deps:
        result = invoke(build_graph(deps), "Hello")
    assert result["trace"] == ["rewrite", "classify", "fixed"]
    assert not result["classification_failed"]
    assert result["reliability_events"][0].repaired
    assert len(model.classified_messages) == 2


def test_repaired_refund_decision_still_obeys_code_checked_window(seeded: Any) -> None:
    from test_refund_flow import FixedRetriever as RefundRetriever
    from test_refund_flow import deps as refund_deps
    from test_refund_flow import invoke as invoke_refund
    from test_refund_flow import yes_decision

    settings, service = seeded
    order = service.get_order("ORD-000001", "CUST-0001")
    main = DecisionFake(responses=["unused"], decisions=[None, yes_decision(order)])
    retriever = RefundRetriever(text="Only refunds within 1 days of purchase are allowed.")
    with refund_deps(settings, service, main, retriever) as deps:
        result = invoke_refund(build_graph(deps), "Refund ORD-000001")

    assert result["trace"] == [
        "rewrite",
        "classify",
        "after_sales",
        "refund_identify",
        "refund_load",
        "refund_retrieve",
        "refund_decide",
        "handoff",
    ]
    assert result["handoff"].reason == "policy_requires_human"
    assert result["refund_request"] is None
    assert main.decision_calls == 2
    event = result["reliability_events"][-1]
    assert event.call_site == "decide"
    assert event.repaired and event.attempts == 2
