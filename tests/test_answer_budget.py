"""The answer prompt fits its token budget by dropping low-ranked sources (no models called).

Found in the 27c memory_short rerun: a catalog chunk that holds a whole product manual made
one answer prompt 46460 tokens against a 12000 budget, and the claim check then overflowed.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from support_agent.config import Settings
from support_agent.gate.evidence import GateResult
from support_agent.graph.deps import GraphDeps
from support_agent.graph.handoff import HandoffReason
from support_agent.graph.intents import Intent
from support_agent.graph.nodes.answer_budget import fit_sources
from support_agent.graph.nodes.knowledge import KnowledgePath
from support_agent.graph.parts import QueryPart
from support_agent.graph.state import ConversationState
from support_agent.retrieval.types import RetrievedChunk
from test_graph_knowledge import evidence, part
from test_multipart_answer import PromptRecordingFake

QUESTION = "What is the return window?"
GATE = GateResult(score=0.9, signals={}, passed=True, threshold=0.7, reason="passed")


def _manual(chunk_id: str = "manual") -> RetrievedChunk:
    """A catalog chunk holding a whole product manual, far over the answer budget."""
    return evidence(0.5)[0].model_copy(
        update={
            "chunk_id": chunk_id,
            "section_id": f"product.{chunk_id}",
            "heading_path": "Catalog > Manual",
            "text": "Table of contents and safety notes. " * 1500,
        }
    )


def _settings() -> Settings:
    settings = Settings()
    settings.grounding.enabled = False
    # The shipped layout: builder on, answer node on the legacy layout.
    assert settings.context.enabled and settings.context.profile_for("answer").legacy_layout
    return settings


def _parts_state(chunks: list[RetrievedChunk]) -> ConversationState:
    numbers = list(range(1, len(chunks) + 1))
    return ConversationState(
        gate=GATE,
        retrieval=chunks,
        messages=[HumanMessage(content=QUESTION)],
        rewritten_query=QUESTION,
        route_source="parts",
        parts=[
            QueryPart(
                text=QUESTION,
                intent=Intent.POLICY_QUESTION,
                gate=GATE,
                source_numbers=numbers,
                retrieval=chunks,
            )
        ],
    )


def test_fit_drops_the_lowest_ranked_source_first_and_keeps_one_per_part() -> None:
    a, b, c, d = (evidence(0.9)[0].model_copy(update={"chunk_id": x}) for x in "abcd")
    candidates = {0: {1: a, 2: b, 3: c}, 1: {4: d}}
    fits_after = {2: True}

    def attempt(kept: dict[int, dict[int, RetrievedChunk]]) -> str | None:
        size = sum(len(sources) for sources in kept.values())
        return "built" if fits_after.get(size) else None

    fitted = fit_sources(candidates, attempt)
    assert fitted is not None
    kept, built, dropped = fitted
    assert kept == {0: {1: a}, 1: {4: d}} and built == "built" and dropped == 2
    assert candidates[0] == {1: a, 2: b, 3: c}, "the input is not changed"
    assert fit_sources(candidates, lambda kept: None) is None


def test_parts_answer_drops_a_low_ranked_manual_instead_of_overflowing() -> None:
    top = evidence(0.99)[0]
    main = PromptRecordingFake(responses=["unused"], payload={"parts": [part(question=QUESTION)]})
    with GraphDeps(_settings(), main_model=main) as deps:
        result = KnowledgePath(deps).answer(_parts_state([top, _manual()]))
    assert main.calls == 1
    prompt = str(main.messages[-1].content)
    assert top.text in prompt and "Table of contents" not in prompt
    assert result["parts"][0].answered


def test_whole_answer_drops_a_low_ranked_manual_instead_of_overflowing() -> None:
    top = evidence(0.99)[0]
    main = PromptRecordingFake(responses=["unused"], payload={"parts": [part()]})
    state = ConversationState(
        gate=GATE,
        retrieval=[top, _manual()],
        messages=[HumanMessage(content=QUESTION)],
        rewritten_query=QUESTION,
    )
    with GraphDeps(_settings(), main_model=main) as deps:
        result = KnowledgePath(deps).answer(state)
    assert main.calls == 1
    prompt = str(main.messages[-1].content)
    assert top.text in prompt and "Table of contents" not in prompt
    assert "30 days. [1]" in result["answer"]


def test_a_single_source_over_budget_hands_off_without_calling_the_model() -> None:
    main = PromptRecordingFake(responses=["unused"], payload={"parts": [part(question=QUESTION)]})
    with GraphDeps(_settings(), main_model=main) as deps:
        result = KnowledgePath(deps).answer(_parts_state([_manual()]))
    assert main.calls == 0
    assert result["handoff"].reason == HandoffReason.CONTEXT_OVERFLOW
    assert result["answer_error_type"] == "ContextOverflow"


def test_the_switch_restores_the_old_over_budget_call() -> None:
    settings = _settings()
    settings.knowledge.fit_answer_budget = False
    main = PromptRecordingFake(responses=["unused"], payload={"parts": [part(question=QUESTION)]})
    with GraphDeps(settings, main_model=main) as deps:
        KnowledgePath(deps).answer(_parts_state([evidence(0.99)[0], _manual()]))
    assert "Table of contents" in str(main.messages[-1].content)
