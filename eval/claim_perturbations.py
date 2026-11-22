"""Seeded construction of unsupported claims with their original citations."""

from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import Decimal
from random import Random

from eval.common import normalised
from eval.schema import ClaimItem, ClaimPerturbation, Section
from support_agent.gate.signals import model_terms
from support_agent.grounding.split import answer_sentences

_CODE = re.compile(r"\b[\w/-]+\b")
_NUMBER = re.compile(
    r"(?<![\w/])(?P<currency>[$£€₹]|USD\s+)?(?P<value>\d+(?:\.\d+)?)"
    r"(?![\w/]|\.\d)(?P<unit>[\s-]*(?:business days?|days?|weeks?|months?|years?|hours?|USD|%))?",
    re.IGNORECASE,
)
_MONEY = frozenset({"usd", "$", "£", "€", "₹"})


class Perturbations:
    def __init__(self, sections: dict[str, Section], support_overlap: float) -> None:
        self.sections = sections
        self.support_overlap = support_overlap
        sections_in_order = [sections[key] for key in sorted(sections)]
        self.models = sorted(
            {
                match.group()
                for section in sections_in_order
                for match in _CODE.finditer(section.text)
                if model_terms(match.group())
            },
            key=lambda model: (model.casefold(), model),
        )
        self.sentences = [
            (section.doc_id, sentence, set(normalised(sentence).split()))
            for section in sections_in_order
            for sentence in answer_sentences(section.text)
            if sentence[0].isalpha() and sentence[-1] in ".!?" and " " in sentence
        ]

    def variants(self, item: ClaimItem, rng: Random) -> Iterable[tuple[ClaimPerturbation, str]]:
        if not item.sources:
            return
        evidence = " " + normalised("\n".join(source.text for source in item.sources)) + " "
        evidence_words = set(evidence.split())
        claim_words = set(normalised(item.claim).split())
        if (
            not claim_words
            or len(claim_words & evidence_words) / len(claim_words) < self.support_overlap
        ):
            return

        def present(term: str) -> bool:
            return f" {normalised(term)} " in evidence

        for match in _NUMBER.finditer(item.claim):
            original = match["value"]
            if not present(original):
                continue
            currency = (match["currency"] or "").strip().casefold()
            unit = (match["unit"] or "").strip(" -").casefold()
            kind: ClaimPerturbation = "number"
            if currency in _MONEY or unit in _MONEY:
                kind = "amount"
            elif unit and unit != "%":
                kind = "duration"

            # Use the next unused number with the same precision and retain the unit.
            changed = Decimal(original) + 1
            while present(str(changed)):
                changed += 1
            start, end = match.span("value")
            yield kind, item.claim[:start] + str(changed) + item.claim[end:]

        model_options = [model for model in self.models if not present(model)]
        for match in _CODE.finditer(item.claim):
            original = match.group()
            if model_options and model_terms(original) and present(original):
                model = rng.choice(model_options)
                yield "model", item.claim[: match.start()] + model + item.claim[match.end() :]

        if all(source.section_id in self.sections for source in item.sources):
            documents = {self.sections[source.section_id].doc_id for source in item.sources}
            foreign = [
                sentence
                for doc, sentence, words in self.sentences
                if doc not in documents
                and words
                and len(words & evidence_words) / len(words) < self.support_overlap
                and not present(sentence)
            ]
            if foreign:
                yield "uncited_sentence", rng.choice(foreign)
