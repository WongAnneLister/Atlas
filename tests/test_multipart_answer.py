"""Offline tests for answer selection after multipart retrieval and gating."""

from typing import Any

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableLambda
from pydantic import Field

from support_agent.config import Settings
from support_agent.gate.evidence import GateResult
from support_agent.graph.deps import GraphDeps
from support_agent.graph.intents import Intent
from support_agent.graph.nodes.knowledge import KnowledgePath
from support_agent.graph.parts import QueryPart
from support_agent.graph.state import ConversationState
from test_graph_knowledge import CoverageFake, evidence, part


class PromptRecordingFake(CoverageFake):
    messages: list[Any] = Field(default_factory=list)

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        runnable = super().with_structured_output(schema, **kwargs)

        def record(messages: list[Any]) -> Any:
            self.messages = messages
            return runnable.invoke(messages)

        return RunnableLambda(record)


def test_only_approved_parts_reach_the_answer_model_and_failed_parts_go_to_handoff() -> None:
    approved = evidence(0.99)[0]
    failed = approved.model_copy(
        update={"chunk_id": "other", "text": "Unrelated policy for failed part."}
    )
    gate = GateResult(score=0.9, signals={}, passed=True, threshold=0.7, reason="passed")
    question = "What is the return window?"
    outside = "Can I pay with gold?"
    main = PromptRecordingFake(responses=["unused"], payload={"parts": [part(question=question)]})
    state = ConversationState(
        gate=gate,
        retrieval=[approved, failed],
        messages=[HumanMessage(content=f"{question} {outside}")],
        rewritten_query=f"{question} {outside}",
        route_source="parts",
        parts=[
            QueryPart(
                text=question,
                intent=Intent.POLICY_QUESTION,
                gate=gate,
                source_numbers=[1],
                retrieval=[approved],
            ),
            QueryPart(
                text=outside,
                intent=Intent.CHITCHAT_OTHER,
                source_numbers=[2],
                retrieval=[failed],
                failure_reason="unsupported_part",
            ),
        ],
    )

    with GraphDeps(Settings(), main_model=main) as deps:
        result = KnowledgePath(deps).answer(state)

    assert main.calls == 1
    assert question in main.messages[-1].content
    assert outside not in main.messages[-1].content
    assert failed.text not in main.messages[-1].content
    assert result["answer_status"] == "partial"
    assert "30 days. [1]" in result["answer"]
    assert outside in result["answer"]
    assert result["handoff"].reason == "unsupported_part"
    assert [item.text for item in result["handoff"].parts] == [outside]
    assert result["handoff"].retrieval_snapshot == [failed]
    assert result["handoff"].rewritten_query == state.rewritten_query
    assert result["parts"][0].answered
    assert result["parts"][0].cited_section_ids == [approved.section_id]
    assert result["parts"][1].handed_off


def test_output_guard_does_not_publish_or_credit_an_unsafe_partial_draft() -> None:
    from support_agent.api.events import events_for_update
    from support_agent.graph.nodes.output_guard import OutputGuard
    from support_agent.graph.state import CitationRecord

    approved = evidence(0.99)[0]
    draft = "A refund is approved. [1]"
    state = ConversationState(
        answer=draft,
        answer_status="partial",
        route_source="parts",
        retrieval=[approved],
        citations=[
            CitationRecord(
                n=1,
                chunk_id=approved.chunk_id,
                section_id=approved.section_id,
                heading_path=approved.heading_path,
            ),
        ],
        parts=[
            QueryPart(
                text="Can I get a refund?",
                answered=True,
                cited_section_ids=[approved.section_id],
            ),
            QueryPart(text="Can I pay with gold?", handed_off=True, failure_reason="low_evidence"),
        ],
    )
    with GraphDeps(Settings()) as deps:
        result = OutputGuard(deps)(state)

    assert result["answer_status"] == "guardrail_blocked"
    assert result["citations"] == []
    assert all(item.handed_off and not item.answered for item in result["parts"])
    assert all(not item.cited_section_ids for item in result["parts"])
    [event] = events_for_update("output_guard", result, 10)
    assert event.name == "handoff"
    assert draft not in event.data["message"]


@pytest.mark.parametrize("reordered", [False, True])
def test_coverage_requires_matching_questions_and_scoped_quotes(reordered: bool) -> None:
    first = evidence(0.99)[0]
    second = first.model_copy(
        update={
            "chunk_id": "gift",
            "section_id": "returns.gift",
            "text": "Gift returns are accepted within 45 days.",
        }
    )
    gate = GateResult(score=0.9, signals={}, passed=True, threshold=0.7, reason="passed")
    first_question = "What is the return window?"
    second_question = "How long do gift returns take?"
    state = ConversationState(
        gate=gate,
        retrieval=[first, second],
        route_source="parts",
        parts=[
            QueryPart(
                text=first_question,
                intent=Intent.POLICY_QUESTION,
                gate=gate,
                source_numbers=[1],
                retrieval=[first],
            ),
            QueryPart(
                text=second_question,
                intent=Intent.POLICY_QUESTION,
                gate=gate,
                source_numbers=[2],
                retrieval=[second],
            ),
        ],
    )
    cross_part_citation = [{"source": 2, "quote": second.text}]
    parts = [
        part(
            "All returns are accepted within 45 days.",
            question=first_question,
            evidence=cross_part_citation,
        ),
        part(second.text, question=second_question, evidence=cross_part_citation),
    ]
    if reordered:
        parts.reverse()
    main = CoverageFake(responses=["unused"], payload={"parts": parts})
    with GraphDeps(Settings(), main_model=main) as deps:
        result = KnowledgePath(deps).answer(state)

    assert "All returns are accepted within 45 days." not in result["answer"]
    if reordered:
        assert result["answer_status"] == "invalid_output"
        assert result["citations"] == []
        assert all(item.handed_off for item in result["parts"])
    else:
        assert result["answer_status"] == "partial"
        assert [item["n"] for item in result["citations"]] == [2]
        assert result["handoff"].parts[0].failure_reason == "invalid_evidence"
        assert result["parts"][1].cited_section_ids == [second.section_id]
