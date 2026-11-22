"""Verify numbered claims with quotes from each claim's cited evidence."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from support_agent.graph.coverage import SourceQuote
from support_agent.grounding.claims import ClaimAssessment, Verdict

if TYPE_CHECKING:
    from support_agent.grounding.claims import Claim
    from support_agent.llm import Role
    from support_agent.reliability.llm_calls import ReliableModels

_PROMPT = Path(__file__).resolve().parents[1] / "graph" / "prompts" / "verify_claims.md"


class Verification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: int = Field(gt=0, strict=True)
    verdict: Verdict
    # One verbatim excerpt per fact: a claim with several facts needs several excerpts.
    evidence: list[SourceQuote] = Field(default_factory=list)


class VerificationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdicts: list[Verification]


def verify_claims(
    models: ReliableModels, role: Role, claims: Sequence[Claim]
) -> dict[int, ClaimAssessment]:
    """Require an individual verdict for every submitted claim in one structured call."""
    if not claims:
        return {}
    by_number = {claim.number: claim for claim in claims}
    if len(by_number) != len(claims):
        raise ValueError("Claim numbers must be unique")

    payload = [
        {
            "number": claim.number,
            "claim": claim.text,
            "question": claim.question,
            "sources": [{"n": source.n, "text": source.text} for source in claim.sources],
        }
        for claim in claims
    ]
    response, _ = models.structured(
        "verify",
        role,
        VerificationBatch,
        [
            SystemMessage(content=_PROMPT.read_text(encoding="utf-8")),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
        ],
        recover=False,
    )
    results = {verdict.number: verdict for verdict in response.value.verdicts}
    if len(results) != len(response.value.verdicts) or results.keys() != by_number.keys():
        raise ValueError("Verifier must return each submitted claim number exactly once")

    assessments = {}
    for number, result in results.items():
        claim = by_number[number]
        verdict = result.verdict
        reason = "verified_quote" if verdict == "supported" else f"verifier_{verdict}"
        if verdict == "supported":
            if not result.evidence:
                raise ValueError("A supported verdict must include a source quote")
            texts = {source.n: " ".join(source.text.split()) for source in claim.sources}
            if not all(
                " ".join(quote.quote.split()) in texts.get(quote.source, "")
                for quote in result.evidence
            ):
                verdict, reason = "unsupported", "invalid_quote"
        assessments[number] = ClaimAssessment(
            part=claim.part, text=claim.text, verdict=verdict, reason=reason
        )
    return assessments
