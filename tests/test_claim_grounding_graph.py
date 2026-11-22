"""Claim grounding on the actual graph with local retrieval and model fakes."""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from support_agent.config import Settings
from support_agent.graph.build import build_graph
from support_agent.graph.deps import GraphDeps
from support_agent.reliability.structured import ParsedResponse
from test_query_planning_graph import MULTIPART_TRACE, RETURNS, SHIPPING, Retriever, chunk

WHOLE = ["input_guard", "rewrite", "classify", "retrieve", "gate", "answer"]
MAIN = "Returns are accepted within 30 days."
SIDE = "Gift wrapping comes with every return."
SHIPPING_FACT = "Customers pay for their own return shipping."


def decision(question, text, *sources):
    return {
        "question": question,
        "supported": True,
        "explicit": True,
        "answer": text,
        "evidence": [{"source": n, "quote": evidence} for n, evidence in sources],
    }


def run_graph(
    monkeypatch,
    *,
    multipart=False,
    answer=None,
    verdicts=None,
    enabled=True,
    partial=True,
    split_compound=False,
    compound_pieces=None,
    followup=False,
):
    settings = Settings()
    settings.grounding.enabled = enabled
    settings.grounding.split_compound = split_compound
    settings.planning.enabled = multipart
    settings.knowledge.partial_answers = partial
    settings.gate.threshold = 0.1
    sources = [chunk("returns", MAIN), chunk("unused", "Unused facts are confidential.")]
    shipping = chunk("shipping", SHIPPING_FACT)
    rows = {RETURNS: sources, SHIPPING: [shipping]}
    model_inputs = {}
    call_sites = []

    def structured(site, role, schema, messages, **kwargs):
        raw = messages[-1].content
        call_sites.append(site)
        if site == "plan":
            value = {
                "is_multi_part": True,
                "parts": [
                    {"text": RETURNS, "key_terms": ["return"]},
                    {"text": SHIPPING, "key_terms": ["shipping"]},
                ],
            }
        elif site == "classify":
            value = {"intent": "policy_question", "confidence": 0.99}
        elif site == "answer":
            value = {"parts": answer}
        elif site in {"verify", "split_claims"}:
            payload = json.loads(raw)
            model_inputs[site] = payload
            assert role == "fast"
            if site == "split_claims":
                [row] = payload
                pieces = compound_pieces
                if pieces is None:
                    first, second = row["text"].split(" and ", maxsplit=1)
                    pieces = [first, "and " + second]
                value = {"splits": [{"number": row["number"], "pieces": pieces}]}
            else:
                if isinstance(verdicts, Exception):
                    raise verdicts
                value = {"verdicts": verdicts}
        else:
            pytest.fail(f"Unexpected model call {site}")
        return ParsedResponse(schema.model_validate(value), "fixture"), None

    retriever = Retriever(rows)
    with GraphDeps(settings, retriever=retriever) as deps:
        monkeypatch.setattr(deps.models, "structured", structured)
        if followup:
            monkeypatch.setattr(
                deps.models, "invoke", lambda *_: (AIMessage(content=RETURNS), None)
            )
        graph = build_graph(deps)
        messages = [HumanMessage(content=RETURNS)]
        if followup:
            messages = [
                HumanMessage(content="Earlier turn"),
                AIMessage(content="Earlier reply"),
                HumanMessage(content="And the deadline?"),
            ]
        if multipart:
            messages = [HumanMessage(content=f"{RETURNS} Also, {SHIPPING}")]
        result = graph.invoke(
            {"messages": messages}, {"configurable": {"thread_id": "grounding-test"}}
        )
    return result, model_inputs, call_sites


def supported(number, source=1, quote=MAIN):
    return {
        "number": number,
        "verdict": "supported",
        "evidence": [{"source": source, "quote": quote}],
    }


def test_ground_retains_only_supported_claims_and_uses_coverage_question(monkeypatch):
    result, inputs, calls = run_graph(
        monkeypatch,
        followup=True,
        answer=[decision(RETURNS, f"{MAIN} {SIDE}", (1, MAIN))],
        verdicts=[supported(1), {"number": 2, "verdict": "partial"}],
    )
    assert result["trace"] == [*WHOLE, "ground", "output_guard"]
    assert result["answer"] == f"{MAIN} [1]"
    assert [row["n"] for row in result["citations"]] == [1]
    assert result["answer_status"] == "answered"
    assert result["claims_removed"] == 1
    assert [claim.removed for claim in result["claims"]] == [False, True]
    assert calls.count("verify") == 1
    assert all(row["question"] == RETURNS for row in inputs["verify"])
    assert all(row["sources"] == [{"n": 1, "text": MAIN}] for row in inputs["verify"])
    assert isinstance(result["messages"][-1], AIMessage)
    assert SIDE not in result["messages"][-1].content


def test_ground_fails_exact_main_without_model_call(monkeypatch):
    result, _, calls = run_graph(
        monkeypatch,
        answer=[decision(RETURNS, "Returns are accepted within 60 days. " + SIDE, (1, MAIN))],
    )
    assert result["trace"] == [*WHOLE, "ground", "handoff", "output_guard"]
    assert result["handoff"].reason == "low_grounding"
    assert not result["citations"] and "60 days" not in result["answer"]
    assert "verify" not in calls


@pytest.mark.parametrize("partial", [True, False])
def test_ground_removes_a_failed_part_and_rebuilds_citations(monkeypatch, partial):
    result, inputs, _ = run_graph(
        monkeypatch,
        multipart=True,
        partial=partial,
        answer=[
            decision(RETURNS, MAIN, (1, MAIN)),
            decision(SHIPPING, SHIPPING_FACT, (3, SHIPPING_FACT)),
        ],
        verdicts=[supported(1), {"number": 2, "verdict": "unsupported"}],
    )
    assert result["trace"] == [*MULTIPART_TRACE, "answer", "ground", "handoff", "output_guard"]
    assert [row["question"] for row in inputs["verify"]] == [RETURNS, SHIPPING]
    assert [row["sources"] for row in inputs["verify"]] == [
        [{"n": 1, "text": MAIN}],
        [{"n": 3, "text": SHIPPING_FACT}],
    ]
    assert result["parts"][1].failure_reason == "low_grounding"
    assert result["handoff"].reason == ("unsupported_part" if partial else "low_grounding")
    assert [row["n"] for row in result["citations"]] == ([1] if partial else [])
    assert (MAIN in result["answer"]) is partial
    assert SHIPPING_FACT not in result["answer"]
    assert all("human support agent" not in row["claim"] for row in inputs["verify"])


@pytest.mark.parametrize(
    ("verdicts", "reason"),
    [
        ([], "low_grounding"),
        ([supported(1), supported(2)], "low_grounding"),
        ([supported(1), supported(1)], "low_grounding"),
        ([{"number": 1, "verdict": "supported"}], "low_grounding"),
        ([{"number": 1, "verdict": "unknown"}], "low_grounding"),
        (ConnectionError("fixture"), "dependency_unavailable"),
    ],
)
def test_ground_invalid_or_unavailable_verifier_does_not_publish(monkeypatch, verdicts, reason):
    result, _, calls = run_graph(
        monkeypatch,
        answer=[decision(RETURNS, MAIN, (1, MAIN))],
        verdicts=verdicts,
    )
    assert result["trace"] == [*WHOLE, "ground", "handoff", "output_guard"]
    assert calls.count("verify") == 1
    assert result["handoff"].reason == reason
    assert not result["citations"]
    assert all(MAIN not in message.content for message in result["messages"])


def test_grounding_off_keeps_legacy_trace_answer_and_citations(monkeypatch):
    result, _, calls = run_graph(
        monkeypatch,
        enabled=False,
        answer=[decision(RETURNS, f"{MAIN} {SIDE}", (1, MAIN))],
    )
    assert result["trace"] == [*WHOLE, "output_guard"]
    assert result["answer"] == f"{MAIN} {SIDE} [1]"
    assert [row["n"] for row in result["citations"]] == [1]
    assert "verify" not in calls
    assert result.get("claims") is None


def test_ground_drops_allowlisted_phrase_from_verifier_input(monkeypatch):
    template = "You can contact support for help."
    result, inputs, _ = run_graph(
        monkeypatch,
        answer=[decision(RETURNS, f"{template} {MAIN}", (1, MAIN))],
        verdicts=[supported(1)],
    )
    assert result["trace"] == [*WHOLE, "ground", "output_guard"]
    assert [row["claim"] for row in inputs["verify"]] == [MAIN]
    assert result["answer"] == f"{template} {MAIN} [1]"


def test_optional_compound_split_reuses_the_original_words(monkeypatch):
    sentence = "Returns are accepted within 30 days and gift wrapping is included."
    result, inputs, calls = run_graph(
        monkeypatch,
        split_compound=True,
        answer=[decision(RETURNS, sentence, (1, MAIN))],
        verdicts=[supported(1), {"number": 2, "verdict": "unsupported"}],
    )
    assert result["trace"] == [*WHOLE, "ground", "output_guard"]
    assert calls[-2:] == ["split_claims", "verify"]
    assert [row["claim"] for row in inputs["verify"]] == [
        "Returns are accepted within 30 days",
        "and gift wrapping is included.",
    ]
    assert result["answer"] == "Returns are accepted within 30 days [1]"


def test_invalid_compound_split_fails_closed_without_verifier(monkeypatch):
    sentence = "Returns are accepted within 30 days and gift wrapping is included."
    result, _, calls = run_graph(
        monkeypatch,
        split_compound=True,
        compound_pieces=["Free returns are available for every purchase."],
        answer=[decision(RETURNS, sentence, (1, MAIN))],
    )
    assert result["trace"] == [*WHOLE, "ground", "handoff", "output_guard"]
    assert result["handoff"].reason == "low_grounding"
    assert calls[-1] == "split_claims"


def test_unsupported_main_withholds_even_a_supported_secondary_claim(monkeypatch):
    result, _, calls = run_graph(
        monkeypatch,
        answer=[decision(RETURNS, f"{MAIN} {SIDE}", (1, MAIN))],
        verdicts=[{"number": 1, "verdict": "unsupported"}, supported(2)],
    )
    assert result["trace"] == [*WHOLE, "ground", "handoff", "output_guard"]
    assert result["handoff"].reason == "low_grounding"
    assert result["claims_removed"] == 2
    assert all(claim.removed for claim in result["claims"])
    assert SIDE not in result["answer"]
    assert calls.count("verify") == 1


def test_whole_route_hands_off_when_second_covered_parts_main_claim_fails(monkeypatch):
    result, inputs, _ = run_graph(
        monkeypatch,
        answer=[decision(RETURNS, MAIN, (1, MAIN)), decision(SHIPPING, SHIPPING_FACT, (1, MAIN))],
        verdicts=[supported(1), {"number": 2, "verdict": "unsupported"}],
    )
    assert result["trace"] == [*WHOLE, "ground", "handoff", "output_guard"]
    assert [row["question"] for row in inputs["verify"]] == [RETURNS, SHIPPING]
    assert [row.part for row in result["claims"]] == [0, 1]
    assert all(row.removed for row in result["claims"])
    assert result["handoff"].reason == "low_grounding"
    assert result["citations"] == []
    assert all(MAIN not in message.content for message in result["messages"])
    assert all(SHIPPING_FACT not in message.content for message in result["messages"])


def test_bad_secondary_quote_removes_that_claim_without_handoff(monkeypatch):
    result, _, _ = run_graph(
        monkeypatch,
        answer=[decision(RETURNS, f"{MAIN} {SIDE}", (1, MAIN))],
        verdicts=[supported(1), supported(2, source=2, quote="Unused facts are confidential.")],
    )
    assert result["trace"] == [*WHOLE, "ground", "output_guard"]
    assert result["answer"] == f"{MAIN} [1]"
    assert result["handoff"] is None
    main, secondary = result["claims"]
    assert main.verdict == "supported" and not main.removed
    assert (secondary.verdict, secondary.reason) == ("unsupported", "invalid_quote")
    assert secondary.removed
