"""Check coverage-validated drafts and release only grounded knowledge replies."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from support_agent.graph.deps import GraphDeps
from support_agent.graph.handoff import HandoffReason, make_handoff, mark_parts_handed_off
from support_agent.graph.nodes.knowledge_reply import multipart_reply, whole_reply
from support_agent.graph.state import ConversationState
from support_agent.grounding.claims import (
    Claim,
    ClaimAssessment,
    ClaimEvidence,
    GroundingDraft,
)
from support_agent.grounding.compound import split_compounds
from support_agent.grounding.exact import missing_literals
from support_agent.grounding.split import answer_fragments
from support_agent.grounding.verify import verify_claims
from support_agent.reliability.guards import diagnostic_type, is_dependency_failure

logger = logging.getLogger(__name__)


@dataclass
class Paragraph:
    draft: GroundingDraft
    fragments: list[str | Claim] = field(default_factory=list)

    def render(self, supported: set[int]) -> str:
        claims = [fragment for fragment in self.fragments if isinstance(fragment, Claim)]
        if not any(claim.number in supported for claim in claims):
            return ""
        if all(claim.number in supported for claim in claims):
            text = self.draft.text.strip()
        else:
            text = " ".join(
                fragment if isinstance(fragment, str) else fragment.text
                for fragment in self.fragments
                if isinstance(fragment, str) or fragment.number in supported
            )
        markers = " ".join(f"[{number}]" for number in self.draft.source_numbers)
        return f"{text} {markers}"


def _claims(paragraphs: list[Paragraph]) -> list[Claim]:
    return [
        fragment
        for paragraph in paragraphs
        for fragment in paragraph.fragments
        if isinstance(fragment, Claim)
    ]


def _first_claims(claims: list[Claim]) -> dict[int, Claim]:
    first: dict[int, Claim] = {}
    for claim in claims:
        first.setdefault(claim.part, claim)
    return first


def _exact_rejections(claims: list[Claim]) -> dict[int, str]:
    rejected = {}
    for claim in claims:
        if not claim.sources:
            rejected[claim.number] = "missing_citation"
        elif missing := missing_literals(claim.text, [source.text for source in claim.sources]):
            rejected[claim.number] = f"missing_literal: {', '.join(missing)}"
    return rejected


def _eligible(claims: list[Claim], rejected: dict[int, str], *, partial: bool) -> list[Claim]:
    blocked = {part for part, claim in _first_claims(claims).items() if claim.number in rejected}
    if blocked and not partial:
        return []
    return [claim for claim in claims if claim.number not in rejected and claim.part not in blocked]


class GroundingPath:
    def __init__(self, deps: GraphDeps) -> None:
        self.deps = deps
        self.settings = deps.settings.grounding

    def _paragraphs(self, state: ConversationState) -> list[Paragraph]:
        paragraphs = []
        number = 0
        for draft in state.grounding_drafts:
            sources = [
                ClaimEvidence(n=n, text=state.retrieval[n - 1].text)
                for n in draft.source_numbers
                if 1 <= n <= len(state.retrieval)
            ]
            paragraph = Paragraph(draft)
            for text, generic in answer_fragments(
                draft.text,
                generic_phrases=self.settings.generic_phrases,
                short_sentence_words=self.settings.short_sentence_words,
            ):
                if generic:
                    paragraph.fragments.append(text)
                    continue
                number += 1
                paragraph.fragments.append(
                    Claim(
                        number=number,
                        part=draft.part,
                        question=draft.question,
                        text=text,
                        sources=sources,
                    )
                )
            paragraphs.append(paragraph)
        return paragraphs

    def _split(self, paragraphs: list[Paragraph], eligible: list[Claim]) -> None:
        splits = split_compounds(self.deps.models, self.settings.verifier_role, eligible)
        number = 0
        for paragraph in paragraphs:
            fragments: list[str | Claim] = []
            for fragment in paragraph.fragments:
                if isinstance(fragment, str):
                    fragments.append(fragment)
                    continue
                for text in splits.get(fragment.number, [fragment.text]):
                    number += 1
                    fragments.append(fragment.model_copy(update={"number": number, "text": text}))
            paragraph.fragments = fragments

    def _assess(self, paragraphs: list[Paragraph], *, partial: bool) -> dict[int, ClaimAssessment]:
        claims = _claims(paragraphs)
        rejected = _exact_rejections(claims)
        eligible = _eligible(claims, rejected, partial=partial)
        if self.settings.split_compound and eligible:
            self._split(paragraphs, eligible)
            claims = _claims(paragraphs)
            rejected = _exact_rejections(claims)
            eligible = _eligible(claims, rejected, partial=partial)
        verdicts = (
            verify_claims(self.deps.models, self.settings.verifier_role, eligible)
            if eligible
            else {}
        )
        assessments = {}
        for claim in claims:
            if claim.number in rejected:
                verdict, reason = "unsupported", rejected[claim.number]
            elif claim.number in verdicts:
                verdict = verdicts[claim.number].verdict
                reason = "verified_quote" if verdict == "supported" else f"verifier_{verdict}"
            else:
                # The part's first claim already failed its exact checks.
                continue
            assessments[claim.number] = ClaimAssessment(
                part=claim.part, text=claim.text, verdict=verdict, reason=reason
            )
        return assessments

    def __call__(self, state: ConversationState) -> dict[str, Any]:
        multipart = state.route_source == "parts"
        partial = multipart and self.deps.settings.knowledge.partial_answers
        trace = [*state.trace, "ground"]
        try:
            paragraphs = self._paragraphs(state)
            assessments = self._assess(paragraphs, partial=partial)
        except Exception as error:
            error_type = diagnostic_type(error)
            logger.warning("Knowledge grounding failed: %s", error_type)
            reason = (
                HandoffReason.DEPENDENCY_UNAVAILABLE
                if is_dependency_failure(error)
                else HandoffReason.LOW_GROUNDING
            )
            return {
                **self._handoff(state, reason, trace),
                "answer_error_type": error_type,
                "claims": [],
                "grounding_drafts": [],
            }

        first = _first_claims(_claims(paragraphs))
        supported = {number for number, row in assessments.items() if row.verdict == "supported"}
        kept_parts = {part for part, claim in first.items() if claim.number in supported}
        failed = {draft.part for draft in state.grounding_drafts} - kept_parts
        release = bool(kept_parts) and (partial or not failed)
        retained = (
            {number for number in supported if assessments[number].part in kept_parts}
            if release
            else set()
        )
        claims = [
            row.model_copy(update={"removed": number not in retained})
            for number, row in assessments.items()
        ]
        update = {
            "grounding_drafts": [],
            "claims": claims,
            "claims_removed": sum(row.removed for row in claims),
        }
        parts = (
            [
                part.model_copy(
                    update={
                        "answered": False,
                        "failure_reason": "low_grounding",
                        "cited_section_ids": [],
                    }
                )
                if index in failed
                else part
                for index, part in enumerate(state.parts)
            ]
            if multipart
            else state.parts
        )
        current = state.model_copy(update={"parts": parts})
        if not release:
            return {**self._handoff(current, HandoffReason.LOW_GROUNDING, trace), **update}
        rendered = [text for paragraph in paragraphs if (text := paragraph.render(retained))]
        if multipart:
            # Retained paragraphs keep their validated paragraph-level citations.
            return {**multipart_reply(current, rendered, trace), **update}
        return {**whole_reply(current, rendered, trace), **update}

    @staticmethod
    def _handoff(
        state: ConversationState, reason: HandoffReason, trace: list[str]
    ) -> dict[str, Any]:
        current = state
        parts_update = {}
        if state.route_source == "parts":
            current = state.model_copy(update={"parts": mark_parts_handed_off(state.parts, reason)})
            parts_update["parts"] = current.parts
        return {
            **make_handoff(current, reason),
            **parts_update,
            "trace": [*trace, "handoff"],
            "citations": [],
            "answer_status": "low_grounding",
        }
