"""Deterministic sentence boundaries for customer-facing claims."""

import re

from support_agent.graph.order_grounding import answer_sentences as order_sentences

CITATION = re.compile(r"\[(\d+)\]")
_ABBREVIATION = re.compile(
    r"(?:\b(?:e\.g|i\.e|mr|mrs|ms|dr|prof|vs|fig|no|approx|etc)\.|(?:\b[A-Za-z]\.){2,})$",
    re.IGNORECASE,
)
_LEADING_CITATIONS = re.compile(r"(?:\[\d+\]\s*)+")


def answer_sentences(answer: str) -> list[str]:
    """Reuse the order splitter and keep abbreviations and citation suffixes intact."""
    sentences: list[str] = []
    for line in answer.splitlines():
        line_sentences: list[str] = []
        for sentence in order_sentences(line):
            if line_sentences and (markers := _LEADING_CITATIONS.match(sentence)):
                line_sentences[-1] += " " + markers.group().strip()
                sentence = sentence[markers.end() :].strip()
            if not sentence:
                continue
            if line_sentences and _ABBREVIATION.search(line_sentences[-1]):
                line_sentences[-1] += " " + sentence
            else:
                line_sentences.append(sentence)
        sentences.extend(line_sentences)
    return sentences
