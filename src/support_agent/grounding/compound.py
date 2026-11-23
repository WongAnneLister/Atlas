"""Optional bounded compound splitting without model-written replacements."""

import json
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from support_agent.grounding.claims import Claim
from support_agent.llm import Role
from support_agent.reliability.llm_calls import ReliableModels

_PROMPT = Path(__file__).resolve().parents[1] / "graph/prompts/split_claims.md"


class ClaimSplit(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    number: int = Field(gt=0, strict=True)
    pieces: list[str] = Field(min_length=1)


class CompoundSplits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    splits: list[ClaimSplit]


def split_compounds(
    models: ReliableModels, role: Role, claims: Sequence[Claim]
) -> dict[int, list[str]]:
    if not claims:
        return {}
    data = [
        {"number": claim.number, "question": claim.question, "text": claim.text} for claim in claims
    ]
    built = models.context_builder().build(
        "split_claims",
        task_prompt=_PROMPT.read_text(encoding="utf-8"),
        user_text=json.dumps(data, ensure_ascii=False),
    )
    response, _ = models.structured(
        "split_claims",
        role,
        CompoundSplits,
        built,
        recover=False,
    )
    splits = {row.number: row.pieces for row in response.value.splits}
    if len(splits) != len(response.value.splits) or splits.keys() != {row.number for row in claims}:
        raise ValueError("Compound splits do not cover the numbered claims")
    for claim in claims:
        pieces = splits[claim.number]
        if any(not piece.strip() for piece in pieces) or " ".join(
            " ".join(pieces).split()
        ) != " ".join(claim.text.split()):
            raise ValueError("Compound splitter changed the original claim")
    return splits
