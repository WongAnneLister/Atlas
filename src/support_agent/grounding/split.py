"""Deterministic sentence boundaries for customer-facing claims."""

import re
from collections.abc import Collection

from support_agent.config import get_settings
from support_agent.graph.order_grounding import answer_sentences as order_sentences

CITATION = re.compile(r"\[(\d+)\]")
_PARAGRAPH = re.compile(r"\n\s*\n")
_ABBREVIATION = re.compile(
    r"(?:\b(?:e\.g|i\.e|mr|mrs|ms|dr|prof|vs|fig|no|approx|etc|rs|usd|eur|gbp|"
    r"inr|kg|mg|cm|mm|oz|lbs?)\.|(?:\b[A-Za-z]\.){2,})$",
    re.IGNORECASE,
)
_LEADING_CITATIONS = re.compile(r"(?:\[\d+\]\s*)+")
_WORDS = re.compile(r"\w+(?:[.,/-]\w+)*")


def sentence_candidates(paragraph: str) -> list[str]:
    """Reuse the order splitter and keep abbreviations and citation suffixes intact."""
    sentences: list[str] = []
    for sentence in order_sentences(paragraph):
        if sentences and (markers := _LEADING_CITATIONS.match(sentence)):
            sentences[-1] += " " + markers.group().strip()
            sentence = sentence[markers.end() :].strip()
        if not sentence:
            continue
        if sentences and _ABBREVIATION.search(sentences[-1]):
            sentences[-1] += " " + sentence
        else:
            sentences.append(sentence)
    return sentences


def _phrase_key(text: str) -> tuple[str, ...]:
    return tuple(_WORDS.findall(CITATION.sub("", text).casefold()))


def answer_fragments(
    answer: str, *, generic_phrases: Collection[str] = (), short_sentence_words: int
) -> list[tuple[str, bool]]:
    """Return claim text and a generic flag, preserving the safe phrases for rendering."""
    ignored = {_phrase_key(phrase) for phrase in generic_phrases}
    fragments: list[tuple[str, bool]] = []
    for paragraph in _PARAGRAPH.split(answer):
        merged: list[tuple[str, bool]] = []
        pending: list[str] = []
        for sentence in sentence_candidates(paragraph):
            words = _phrase_key(sentence)
            if words in ignored:
                if pending:
                    merged.append((" ".join(pending), False))
                    pending.clear()
                merged.append((sentence, True))
                continue
            pending.append(sentence)
            if len(words) > short_sentence_words:
                merged.append((" ".join(pending), False))
                pending.clear()
        if pending:
            if merged and not merged[-1][1]:
                merged[-1] = (merged[-1][0] + " " + " ".join(pending), False)
            else:
                merged.append((" ".join(pending), False))
        fragments.extend(merged)
    return fragments


def answer_sentences(answer: str, *, generic_phrases: Collection[str] = ()) -> list[str]:
    """Use the same fragment boundaries as runtime verification."""
    return [
        text
        for text, generic in answer_fragments(
            answer,
            generic_phrases=generic_phrases,
            short_sentence_words=get_settings().grounding.short_sentence_words,
        )
        if not generic
    ]
