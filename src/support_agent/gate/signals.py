"""Deterministic evidence features for reranked retrieval results."""

from __future__ import annotations

import re
import unicodedata

from support_agent.config import GateSettings
from support_agent.retrieval.bm25 import normalise_model_numbers
from support_agent.retrieval.types import RetrievedChunk

_MODEL_NUMBER = re.compile(
    r"\b(?=[A-Z0-9/-]{3,}\b)(?=[A-Z0-9/-]*\d)[A-Z][A-Z0-9]*(?:[-/][A-Z0-9]+)*\b",
    re.IGNORECASE,
)
_NUMBER_UNIT = re.compile(
    r"(?:[$£€]\s?\d+(?:[.,]\d+)?|"
    r"(?<!\w)\d+(?:[.,]\d+)?\s?(?:%|days?|weeks?|months?|years?|hours?|usd|inches?|cm|mm|kg|g|ml|l)(?!\w))",
    re.IGNORECASE,
)
_WORD = re.compile(r"\w+", re.UNICODE)


def _normalise(text: str) -> str:
    model_normalised = normalise_model_numbers(unicodedata.normalize("NFKC", text))
    return " ".join(_WORD.findall(model_normalised.casefold()))


def top_score(chunks: list[RetrievedChunk]) -> float:
    """Return the top sigmoid rerank score, or zero without evidence."""
    if not chunks:
        return 0.0
    return min(1.0, max(0.0, chunks[0].scores.get("rerank", 0.0)))


def good_count(chunks: list[RetrievedChunk], settings: GateSettings) -> float:
    count = sum(chunk.scores.get("rerank", 0.0) >= settings.good_evidence_min for chunk in chunks)
    return min(count, settings.good_count_cap) / settings.good_count_cap


def margin(chunks: list[RetrievedChunk]) -> float:
    if not chunks:
        return 0.0
    if len(chunks) == 1:
        return 1.0
    difference = chunks[0].scores.get("rerank", 0.0) - chunks[1].scores.get("rerank", 0.0)
    return min(1.0, max(0.0, difference))


def key_terms(query: str, settings: GateSettings) -> list[str]:
    terms = [match.group(0) for match in _MODEL_NUMBER.finditer(query)]
    terms.extend(match.group(0) for match in _NUMBER_UNIT.finditer(query))
    normalised_query = _normalise(query)
    terms.extend(
        noun for noun in settings.policy_nouns if f" {_normalise(noun)} " in f" {normalised_query} "
    )
    return list(dict.fromkeys(_normalise(term) for term in terms if _normalise(term)))


def key_hit(query: str, chunks: list[RetrievedChunk], settings: GateSettings) -> float:
    terms = key_terms(query, settings)
    if not terms:
        return 1.0
    corpus = _normalise(" ".join(chunk.text for chunk in chunks[:3]))
    return sum(f" {term} " in f" {corpus} " for term in terms) / len(terms)
