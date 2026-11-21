from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from support_agent.api.events import events_for_update
from support_agent.config import Settings
from support_agent.graph.deps import GraphDeps
from support_agent.graph.handoff import load_templates
from support_agent.graph.nodes.output_guard import OutputGuard
from support_agent.graph.state import CitationRecord, ConversationState
from support_agent.guardrails.output import OutputChecks
from support_agent.retrieval.types import RetrievedChunk


def checks(tmp_path: Path) -> OutputChecks:
    (tmp_path / "private.md").write_text(
        "The private instructions contain this deliberately unique sentence for the silent tool.",
        encoding="utf-8",
    )
    settings = Settings().guardrails.output
    settings.prompt_word_window = 8
    return OutputChecks(settings, tmp_path)


def test_prompt_overlap_uses_full_word_window(tmp_path: Path) -> None:
    guard = checks(tmp_path)
    assert guard.prompt_leaked("private instructions contain this deliberately unique sentence for")
    assert not guard.prompt_leaked("private instructions for the silent tool")
    # No rule knows the evaluation's canary format; only real prompt text counts.
    assert not guard.prompt_leaked("ATLAS-CANARY-" + "abc123" * 2)


@pytest.mark.parametrize(
    ("answer", "blocked"),
    [
        ("Only me at alex@example.com.", False),
        ("Write to someone@example.com.", True),
        ("Their number is +1 (415) 555-0131.", True),
        ("Card 4111 1111 1111 1111.", True),
        ("Order ORD-000356 ships on 2026-05-15.", False),
    ],
)
def test_foreign_pii_checks_only_owned_email(tmp_path: Path, answer: str, blocked: bool) -> None:
    assert checks(tmp_path).foreign_pii(answer, "alex@example.com") is blocked


def test_business_contacts_quoted_from_evidence_are_not_foreign_pii(tmp_path: Path) -> None:
    # Shapes taken from the policy corpus: a support line and a support mailbox.
    source = "Call us on 1800-209-9090 or write to group.care@aegonlife.com for claims."
    guard = checks(tmp_path)
    answer = "You can call 1800 209 9090 or email group.care@aegonlife.com. [1]"
    assert not guard.foreign_pii(answer, None, [source])
    assert guard.foreign_pii(answer, None, [])
    assert guard.foreign_pii("Email other.person@example.com instead.", None, [source])


def test_output_guard_reads_cited_sources_as_evidence() -> None:
    from support_agent.graph.nodes.output_guard import _evidence

    chunk = RetrievedChunk(
        chunk_id="contact",
        doc_id="contact",
        section_id="contact.help",
        title="Contact",
        heading_path="Contact",
        text="Call 1800-209-9090.",
        n_tokens=3,
        scores={},
    )
    cited = CitationRecord(n=1, chunk_id="contact", section_id="contact.help", heading_path="C")
    state = ConversationState(retrieval=[chunk], citations=[cited], order_context={"a": 1})
    assert _evidence(state) == ["Call 1800-209-9090.", '{"a": 1}']
    assert _evidence(state.model_copy(update={"citations": []})) == ['{"a": 1}']


def test_production_code_has_no_evaluation_marker_rules() -> None:
    from support_agent.config import REPO_ROOT

    for path in (REPO_ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8").casefold()
        assert "canary" not in text, path


def test_commitment_needs_the_terms_and_amount_in_its_citation(tmp_path: Path) -> None:
    policy = RetrievedChunk(
        chunk_id="policy",
        doc_id="policy",
        section_id="policy.window",
        title="Policy",
        heading_path="Policy",
        text="We will issue a $10 discount when the item is eligible.",
        n_tokens=10,
        scores={},
    )
    citation = CitationRecord(
        n=1, chunk_id="policy", section_id="policy.window", heading_path="Policy"
    )
    state = ConversationState(
        answer="We will issue a $10 discount. [1]",
        citations=[citation],
        retrieval=[policy],
    )
    guard = checks(tmp_path)
    assert not guard.unbacked_commitment(state)
    assert guard.unbacked_commitment(
        state.model_copy(update={"answer": "A $90 discount is approved. [1]"})
    )
    assert guard.unbacked_commitment(state.model_copy(update={"citations": []}))
    assert not guard.unbacked_commitment(
        state.model_copy(update={"answer": "We cannot promise compensation."})
    )


def test_order_facts_back_delivery_date_and_safe_templates_pass(tmp_path: Path) -> None:
    guard = checks(tmp_path)
    assert not guard.unbacked_commitment(
        ConversationState(
            answer="It will arrive on 2026-11-27.",
            order_context={"get_tracking": {"expected_delivery": "2026-11-27"}},
        )
    )
    canned = [
        load_templates("fixed_replies.yaml")["complaint_acknowledgement"],
        load_templates("handoff_messages.yaml")["complaint"],
        "Your refund request REF-123 is pending human review. [1]",
        "I cannot approve this request. You can ask a human agent to review it. [1]",
    ]
    assert not any(guard.unbacked_commitment(ConversationState(answer=reply)) for reply in canned)


def test_output_guard_replaces_unsafe_answer_before_sse() -> None:
    answer = "A discount is approved."
    state = ConversationState(
        answer=answer,
        messages=[HumanMessage(content="Can you help?"), AIMessage(id="unsafe", content=answer)],
    )
    with GraphDeps(Settings()) as deps:
        final = OutputGuard(deps)(state)
    assert events_for_update("answer", {"answer": answer}, 1) == []
    [event] = events_for_update("output_guard", final, 1)
    assert event.name == "handoff" and event.data["reason"] == "guardrail_blocked"
    assert answer not in str(event.data)
    assert final["messages"][0].id == "unsafe"
    assert answer not in str(final["handoff"].conversation)


def test_refund_approval_is_not_backed_by_a_topical_policy(tmp_path: Path) -> None:
    retrieved = RetrievedChunk(
        chunk_id="source",
        doc_id="policy",
        section_id="returns",
        title="Returns",
        heading_path="Returns",
        text="Customers can request a refund under the policy.",
        n_tokens=10,
        scores={},
    )
    state = ConversationState(
        answer="I approved your refund. [1]",
        retrieval=[retrieved],
        citations=[
            CitationRecord(n=1, chunk_id="source", section_id="returns", heading_path="Returns")
        ],
    )
    assert checks(tmp_path).unbacked_commitment(state)
    assert checks(tmp_path).unbacked_commitment(
        state.model_copy(update={"answer": "I cannot promise credit, but a discount is approved."})
    )


def test_interrupted_output_is_not_added_to_next_turn_history(monkeypatch) -> None:
    from support_agent.graph.build import build_graph
    from support_agent.graph.intents import Intent
    from support_agent.graph.nodes.knowledge import KnowledgePath
    from test_graph import fake
    from test_graph_knowledge import FixedRetriever, evidence

    private = "Private draft at witness@example.com"

    def candidate(self, state):
        return {
            "answer": private,
            "messages": [AIMessage(content=private)],
            "trace": [*state.trace, "answer"],
        }

    monkeypatch.setattr(KnowledgePath, "answer", candidate)
    model = fake(Intent.POLICY_QUESTION, Intent.CHITCHAT_OTHER, rewrite="Hello again")
    settings = Settings()
    settings.gate.threshold = 0.5
    config = {"configurable": {"thread_id": "interrupted-draft"}}
    with GraphDeps(settings, fast_model=model, retriever=FixedRetriever(evidence(0.99))) as deps:
        graph = build_graph(deps)
        graph.invoke(
            {"messages": [HumanMessage(content="What is the return policy?")]},
            config,
            interrupt_before=["output_guard"],
        )
        graph.invoke({"messages": [HumanMessage(content="Hello again")]}, config)
    assert model.rewritten_messages
    assert private not in str(model.rewritten_messages[0])
