from __future__ import annotations

import json
from typing import Any

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from support_agent.config import Settings
from support_agent.graph.deps import GraphDeps
from support_agent.grounding.claims import Claim, ClaimEvidence
from support_agent.grounding.verify import verify_claims
from support_agent.reliability.structured import ParsedResponse


def claims() -> list[Claim]:
    return [
        Claim(
            number=1,
            part=0,
            text="The refund window is 30 days.",
            question="Is the refund window 90 days?",
            sources=[ClaimEvidence(n=1, text="Original returns take\n  30 days.")],
        ),
        Claim(
            number=3,
            part=1,
            text="Shipping is free.",
            question="Is shipping free?",
            sources=[ClaimEvidence(n=2, text="Shipping costs 10 dollars.")],
        ),
    ]


SUPPORT = {
    "number": 1,
    "verdict": "supported",
    "evidence": [{"source": 1, "quote": "returns take 30 days"}],
}
UNSUPPORTED = {"number": 3, "verdict": "partial"}


def verifier(monkeypatch: pytest.MonkeyPatch, model: Any, rows: list[dict[str, Any]]) -> list:
    calls = []

    def structured(site, role, schema, messages, *, recover):
        calls.append((site, role, messages, recover))
        return ParsedResponse(schema.model_validate({"verdicts": rows}), "fixture"), None

    monkeypatch.setattr(model, "structured", structured)
    return calls


def test_one_verifier_call_preserves_each_claims_context_and_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with GraphDeps(Settings()) as deps:
        calls = verifier(monkeypatch, deps.models, [UNSUPPORTED, SUPPORT])
        result = verify_claims(deps.models, "fast", claims())

    [(site, role, messages, recover)] = calls
    assert (site, role, recover) == ("verify", "fast", False)
    instructions, payload = messages
    assert isinstance(instructions, SystemMessage)
    assert isinstance(payload, HumanMessage)
    assert "The question supplies context only" in instructions.content
    assert json.loads(payload.content) == [
        {
            "number": 1,
            "claim": "The refund window is 30 days.",
            "question": "Is the refund window 90 days?",
            "sources": [{"n": 1, "text": "Original returns take\n  30 days."}],
        },
        {
            "number": 3,
            "claim": "Shipping is free.",
            "question": "Is shipping free?",
            "sources": [{"n": 2, "text": "Shipping costs 10 dollars."}],
        },
    ]
    assert {number: checked.verdict for number, checked in result.items()} == {
        1: "supported",
        3: "partial",
    }


@pytest.mark.parametrize(
    "rows",
    [
        [SUPPORT],  # Missing claim
        [SUPPORT, SUPPORT],  # Duplicate number
        [SUPPORT, UNSUPPORTED, {"number": 4, "verdict": "unsupported"}],  # Extra claim
        [{"number": 1, "verdict": "supported"}, UNSUPPORTED],  # Missing quote
        [{"number": 1, "verdict": "unknown"}, UNSUPPORTED],  # Schema error
    ],
)
def test_verifier_rejects_structurally_invalid_batches(
    monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]]
) -> None:
    with GraphDeps(Settings()) as deps:
        calls = verifier(monkeypatch, deps.models, rows)
        with pytest.raises(ValueError):
            verify_claims(deps.models, "fast", claims())
    assert len(calls) == 1


def test_verifier_does_not_call_model_without_claims(monkeypatch: pytest.MonkeyPatch) -> None:
    with GraphDeps(Settings()) as deps:
        calls = verifier(monkeypatch, deps.models, [])
        assert verify_claims(deps.models, "fast", []) == {}
    assert calls == []


@pytest.mark.parametrize(
    "evidence",
    [
        [{"source": 2, "quote": "Shipping costs 10 dollars."}],
        [{"source": 1, "quote": "90 days"}],
        # Fragments joined with an ellipsis are not one verbatim excerpt.
        [{"source": 1, "quote": "returns ... 30 days"}],
        # Every excerpt must be verbatim, not just one of them.
        [{"source": 1, "quote": "returns take 30 days"}, {"source": 1, "quote": "90 days"}],
    ],
)
def test_verifier_marks_only_the_claim_with_an_invalid_quote(monkeypatch, evidence):
    with GraphDeps(Settings()) as deps:
        calls = verifier(monkeypatch, deps.models, [{**SUPPORT, "evidence": evidence}, UNSUPPORTED])
        result = verify_claims(deps.models, "fast", claims())
    assert len(calls) == 1
    assert (result[1].verdict, result[1].reason) == ("unsupported", "invalid_quote")
    assert result[3].verdict == "partial"


def test_verifier_accepts_one_verbatim_excerpt_per_fact(monkeypatch):
    two_facts = {
        **SUPPORT,
        "evidence": [
            {"source": 1, "quote": "returns take 30 days"},
            {"source": 1, "quote": "30 days"},
        ],
    }
    with GraphDeps(Settings()) as deps:
        verifier(monkeypatch, deps.models, [two_facts, UNSUPPORTED])
        result = verify_claims(deps.models, "fast", claims())
    assert (result[1].verdict, result[1].reason) == ("supported", "verified_quote")


def test_supported_without_any_excerpt_is_a_structural_failure(monkeypatch):
    with GraphDeps(Settings()) as deps:
        verifier(monkeypatch, deps.models, [{**SUPPORT, "evidence": []}, UNSUPPORTED])
        with pytest.raises(ValueError, match="quote"):
            verify_claims(deps.models, "fast", claims())
