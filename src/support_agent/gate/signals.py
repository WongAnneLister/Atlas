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
# Words joined only by spaces; any punctuation ends a name.
_NAME_TOKEN = re.compile(r"[^\W_][\w'\u2019&+/-]*|[^\w\s]+", re.UNICODE)


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


def _capitalised(token: str, stopwords: set[str]) -> bool:
    if not token[0].isalpha() and not token[0].isdigit():
        return False
    has_upper = token[0].isupper() or any(char.isupper() for char in token[1:])
    return has_upper and token.casefold() not in stopwords and not token.isdigit()


def _plain_titlecase(token: str) -> bool:
    """'Explain' is plain title case; 'PhonePe', 'BHD340' and 'OTP' are not."""
    return token[0].isupper() and not any(c.isupper() or c.isdigit() for c in token[1:])


def entity_terms(query: str, settings: GateSettings) -> list[str]:
    """Return runs of capitalised words, minus store names and non-name words.

    A plain title-case word that opens a sentence is ordinary capitalisation, not a name.
    """
    stopwords = {word.casefold() for word in settings.entity_stopwords}
    scope = {_normalise(term) for term in settings.scope_terms}
    names: list[str] = []
    current: list[str] = []
    sentence_start = True
    for match in _NAME_TOKEN.finditer(unicodedata.normalize("NFKC", query)):
        token = match.group(0)
        opens_sentence = sentence_start
        sentence_start = not token[0].isalnum() and any(mark in token for mark in ".?!:;")
        if (
            token[0].isalnum()
            and _capitalised(token, stopwords)
            and not (opens_sentence and _plain_titlecase(token))
        ):
            current.append(token)
            continue
        if current:
            names.append(" ".join(current))
        current = []
    if current:
        names.append(" ".join(current))
    models = {_normalise(match.group(0)) for match in _MODEL_NUMBER.finditer(query)}
    kept = [name for name in names if _normalise(name) not in scope | models]
    return list(dict.fromkeys(term for term in (_normalise(name) for name in kept) if term))


def model_terms(query: str) -> list[str]:
    """Extract normalized model codes using the gate's matching rules."""
    return list(
        dict.fromkeys(_normalise(match.group(0)) for match in _MODEL_NUMBER.finditer(query))
    )


def specific_terms(query: str, settings: GateSettings) -> list[str]:
    """Model numbers and, when enabled, named entities: the things a question is about."""
    terms = model_terms(query)
    if settings.entity_terms:
        terms.extend(entity_terms(query, settings))
    return list(dict.fromkeys(term for term in terms if term))


def key_terms(query: str, settings: GateSettings) -> list[str]:
    terms = specific_terms(query, settings)
    terms.extend(_normalise(match.group(0)) for match in _NUMBER_UNIT.finditer(query))
    normalised_query = _normalise(query)
    terms.extend(
        _normalise(noun)
        for noun in settings.policy_nouns
        if f" {_normalise(noun)} " in f" {normalised_query} "
    )
    return list(dict.fromkeys(term for term in terms if term))


def _evidence_text(chunks: list[RetrievedChunk], settings: GateSettings) -> str:
    return " " + _normalise(" ".join(c.text for c in chunks[: settings.key_hit_top_chunks])) + " "


def key_hit(query: str, chunks: list[RetrievedChunk], settings: GateSettings) -> float | None:
    """Share of key terms found in the top chunks; None when excluded for a term-free query."""
    terms = key_terms(query, settings)
    if not terms:
        return None if settings.key_hit_without_terms == "exclude" else 1.0
    corpus = _evidence_text(chunks, settings)
    return sum(f" {term} " in corpus for term in terms) / len(terms)


def specific_term_missed(query: str, chunks: list[RetrievedChunk], settings: GateSettings) -> bool:
    """True when the query names models or entities and none of them is in the top chunks."""
    terms = specific_terms(query, settings)
    if not terms:
        return False
    corpus = _evidence_text(chunks, settings)
    return not any(f" {term} " in corpus for term in terms)


def model_number_missed(query: str, chunks: list[RetrievedChunk], settings: GateSettings) -> bool:
    """True when the query names model numbers and none of them is in the top chunks.

    Stricter than specific_term_missed: a hit on another name (e.g. "USB") does not
    stand in for the model. One model is enough, so "X, rather than Y" still passes.
    """
    models = model_terms(query)
    if not models:
        return False
    corpus = _evidence_text(chunks, settings)
    return not any(f" {model} " in corpus for model in models)
