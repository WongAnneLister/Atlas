"""Seeded construction of unsupported claims with their original citations."""

from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import Decimal
from random import Random

from eval.common import normalised
from eval.schema import ClaimItem, ClaimPerturbation, Section
from support_agent.config import get_settings
from support_agent.gate.signals import model_terms
from support_agent.grounding.split import sentence_candidates

_CODE = re.compile(r"\b[\w/-]+\b")
_NUMBER = re.compile(
    r"(?<![\w/])(?P<currency>[$£€₹]|(?:USD|EUR|GBP|INR|Rs\.?)\s+)?(?P<value>\d+(?:\.\d+)?)"
    r"(?![\w/]|\.\d)(?P<unit>[\s-]*(?:business days?|days?|weeks?|months?|years?|hours?|"
    r"minutes?|seconds?|USD|EUR|GBP|INR|Rs\.?|%))?",
    re.IGNORECASE,
)
_MONEY = frozenset({"usd", "eur", "gbp", "inr", "rs", "rs.", "$", "£", "€", "₹"})

_LINK = re.compile(r"https?://|www\.|\[[^\]]+\]\(|<a\b", re.IGNORECASE)
_NAVIGATION = re.compile(
    r"^(?:click|tap|read more|learn more|see also|visit|go to|refer to|for more)\b", re.IGNORECASE
)
_PREDICATE = re.compile(
    r"\b(?:is|are|was|were|has|have|can|may|must|will|includes?|takes?|costs?|covers?|"
    r"ships?|closes?|opens?|requires?|supports?|provides?|applies|expires?)\b",
    re.IGNORECASE,
)


def _factual_sentences(text: str, min_words: int) -> Iterable[tuple[str, set[str]]]:
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        for sentence in sentence_candidates(line):
            words = normalised(sentence).split()
            if (
                len(words) >= min_words
                and sentence[0].isalnum()
                and sentence[-1] in ".!"
                and _PREDICATE.search(sentence)
                and not _LINK.search(sentence)
                and not _NAVIGATION.match(sentence)
            ):
                yield sentence, set(words)


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
        min_words = get_settings().eval.claims.foreign_min_words
        self.sentences = [
            (section.doc_id, sentence, words)
            for section in sections_in_order
            for sentence, words in _factual_sentences(section.text, min_words)
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
                and len(words & evidence_words) / len(words) < self.support_overlap
                and not present(sentence)
            ]
            if foreign:
                yield "uncited_sentence", rng.choice(foreign)
