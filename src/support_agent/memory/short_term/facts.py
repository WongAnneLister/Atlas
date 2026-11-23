"""Typed pinned facts with regex extraction, self-correction superseding, and stable rendering."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from support_agent.reliability.llm_calls import ReliableModels

logger = logging.getLogger(__name__)

FactKind = Literal[
    "order_id",
    "model_number",
    "date",
    "amount",
    "problem",
    "decision",
    "handoff_status",
]

_ORDER_ID_RE = re.compile(r"\bORD-\d+\b", re.IGNORECASE)
_MODEL_RE = re.compile(
    r"\b(?:BHD\d+/\d+|HD\d+X?|TAH\d+|\d+E\d+N\d+A|W40\s+Pro|W400|W40)\b",
    re.IGNORECASE,
)
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_AMOUNT_RE = re.compile(r"\$\d+(?:\.\d{2})?")
_CORRECTION_RE = re.compile(
    r"\b(?:sorry|meant|actually|instead|correction|wrong\s+order|not\s+ORD-\d+)\b",
    re.IGNORECASE,
)


class PinnedFact(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: FactKind
    value: str = Field(min_length=1)
    source_turn: int = Field(ge=1)
    verbatim: str | None = None
    superseded_by: str | None = None


class _ExtractedProblem(BaseModel):
    problem: str | None = None
    decision: str | None = None


class PinnedFacts(BaseModel):
    entries: list[PinnedFact] = Field(default_factory=list)

    def add(
        self,
        kind: FactKind,
        value: str,
        source_turn: int,
        *,
        verbatim: str | None = None,
        supersede_previous: bool = False,
    ) -> PinnedFacts:
        clean = value.strip()
        if not clean:
            return self
        updated: list[PinnedFact] = []
        already_active = False
        for entry in self.entries:
            if entry.kind == kind and entry.superseded_by is None:
                if entry.value.casefold() == clean.casefold():
                    already_active = True
                    updated.append(entry)
                elif supersede_previous:
                    updated.append(entry.model_copy(update={"superseded_by": clean}))
                else:
                    updated.append(entry)
            else:
                updated.append(entry)
        if not already_active:
            updated.append(
                PinnedFact(
                    kind=kind,
                    value=clean,
                    source_turn=source_turn,
                    verbatim=verbatim,
                )
            )
        return PinnedFacts(entries=updated)

    def active(self, kind: FactKind | None = None) -> list[PinnedFact]:
        items = [e for e in self.entries if e.superseded_by is None]
        if kind is not None:
            items = [e for e in items if e.kind == kind]
        return sorted(items, key=lambda e: (e.kind, e.source_turn, e.value))

    def latest_order_id(self) -> str | None:
        orders = self.active("order_id")
        if not orders:
            return None
        return max(orders, key=lambda e: e.source_turn).value

    def render_dict(self) -> dict[str, Any]:
        """Deterministic rendering for L4_turn: current facts sorted by kind, then turn."""
        if not self.entries:
            return {}
        current: dict[str, list[dict[str, Any]]] = {}
        for entry in self.active():
            row: dict[str, Any] = {"value": entry.value, "turn": entry.source_turn}
            if entry.verbatim:
                row["verbatim"] = entry.verbatim
            current.setdefault(entry.kind, []).append(row)
        corrections = [
            f"{e.kind}: {e.value} superseded by {e.superseded_by}"
            for e in sorted(self.entries, key=lambda x: (x.kind, x.source_turn, x.value))
            if e.superseded_by is not None
        ]
        result: dict[str, Any] = {"current": current}
        if corrections:
            result["corrections"] = corrections
        return result


def extract_facts_from_turn(
    text: str,
    turn_index: int,
    existing: PinnedFacts,
    *,
    models: ReliableModels | None = None,
    use_llm: bool = False,
) -> PinnedFacts:
    """Extract customer-visible facts via regex first, with optional fast-model extraction."""
    if not text.strip():
        return existing
    is_correction = bool(_CORRECTION_RE.search(text))
    facts = existing

    order_ids = list(dict.fromkeys(m.group(0).upper() for m in _ORDER_ID_RE.finditer(text)))
    if is_correction and order_ids:
        # On a correction ("not ORD-1, I meant ORD-2"), keep the last mentioned ID.
        chosen = order_ids[-1]
        facts = facts.add("order_id", chosen, turn_index, supersede_previous=True)
    else:
        for oid in order_ids:
            facts = facts.add("order_id", oid, turn_index, supersede_previous=False)

    models_found = list(dict.fromkeys(m.group(0).upper() for m in _MODEL_RE.finditer(text)))
    for model_code in models_found:
        facts = facts.add("model_number", model_code, turn_index, supersede_previous=is_correction)

    for day in dict.fromkeys(m.group(0) for m in _DATE_RE.finditer(text)):
        facts = facts.add("date", day, turn_index)

    for amount in dict.fromkeys(m.group(0) for m in _AMOUNT_RE.finditer(text)):
        facts = facts.add("amount", amount, turn_index)

    if use_llm and models is not None:
        try:
            built = models.context_builder().build(
                "extract_facts",
                task_prompt=(
                    "Extract a short verbatim customer problem statement or decision if present. "
                    "Return null fields if none."
                ),
                user_text=text,
            )
            parsed, _ = models.structured(
                "extract_facts", "fast", _ExtractedProblem, built, recover=False
            )
            if parsed.value.problem and parsed.value.problem.strip():
                facts = facts.add(
                    "problem",
                    parsed.value.problem.strip(),
                    turn_index,
                    verbatim=parsed.value.problem.strip(),
                )
            if parsed.value.decision and parsed.value.decision.strip():
                facts = facts.add("decision", parsed.value.decision.strip(), turn_index)
        except Exception as error:
            logger.debug("LLM fact extraction skipped: %s", type(error).__name__)

    return facts
