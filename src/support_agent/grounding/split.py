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
# An inline list item number: "1. Go to ...", inside a sentence rather than at a line start.
_INLINE_ITEM = re.compile(r"(?:(?<=\s)|^)(\d{1,2})\.\s+(?=[A-Z])")


def _break_inline_list(paragraph: str) -> str:
    """Start a new line at each item of an inline list numbered 1, 2, 3 ...

    A lone "40. You ..." is not a list: at least items 1 and 2 must appear in order.
    The order splitter then drops the item numbers as line-start list markers.
    """
    items = []
    for match in _INLINE_ITEM.finditer(paragraph):
        if int(match.group(1)) == len(items) + 1:
            items.append(match)
    if len(items) < 2:
        return paragraph
    pieces, start = [], 0
    for match in items:
        pieces.append(paragraph[start : match.start()].rstrip())
        start = match.start()
    pieces.append(paragraph[start:])
    return "\n".join(piece for piece in pieces if piece)


def sentence_candidates(paragraph: str) -> list[str]:
    """Reuse the order splitter and keep abbreviations and citation suffixes intact."""
    sentences: list[str] = []
    for sentence in order_sentences(_break_inline_list(paragraph)):
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
