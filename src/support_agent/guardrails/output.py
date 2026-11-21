"""Check the final reply against private prompts and this turn's evidence."""

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from support_agent.graph.order_grounding import answer_sentences
from support_agent.graph.state import ConversationState
from support_agent.guardrails.pii import find_pii
from support_agent.guardrails.settings import OutputGuardSettings

OutputFlag = Literal["prompt_leak", "foreign_pii", "unbacked_commitment"]

_WORD = re.compile(r"\w+")
_CLAUSE = re.compile(r"[;,]?\s+\b(?:but|however)\b[, ]+", re.IGNORECASE)
_REFUND_APPROVAL = re.compile(
    r"\brefund\s+(?:(?:has been|is|was)\s+)?approved\b|"
    r"\bapprov\w*\s+(?:(?:your|this|the|a)\s+)?refund\b",
    re.IGNORECASE,
)
_DELIVERY_GUARANTEE = re.compile(r"\b(?:guarantee|promise)\w*\b", re.IGNORECASE)
_MARKER = re.compile(r"\[(\d+)\]")
_TERMS = {
    "refund": re.compile(r"\brefund(?:ed|s)?\b", re.IGNORECASE),
    "compensation": re.compile(r"\bcompensat\w*\b", re.IGNORECASE),
    "discount": re.compile(r"\bdiscount\w*\b", re.IGNORECASE),
    "credit": re.compile(r"\bcredit(?:ed|s)?\b", re.IGNORECASE),
    "delivery": re.compile(r"\b(?:arriv\w*|deliver\w*)\b", re.IGNORECASE),
}
_PROMISE = re.compile(
    r"\b(?:will|guarantee\w*|promise\w*|approv\w*|expect\w*|commit(?:ment)?|"
    r"you(?:'ll|\u2019ll)|is scheduled)\b",
    re.IGNORECASE,
)
_NEGATION = re.compile(
    r"\b(?:cannot|can't|can\u2019t|won't|won\u2019t|not|unable)\s+"
    r"(?:(?:be|to)\s+)?(?:guarantee|promise|approve|issue|refund|receive|offer|be)\b",
    re.IGNORECASE,
)
_DATE = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"today|tomorrow|(?:january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\s+\d{1,2}|"
    r"\d{1,2}/\d{1,2}/\d{2,4}|(?:in|within)\s+\d+\s+days?)\b",
    re.IGNORECASE,
)
_NUMERIC = re.compile(r"[$£€]\s*\d+(?:\.\d+)?|\b\d+(?:\.\d+)?\s*%")


def _normal(text: str) -> str:
    return " ".join(text.casefold().split())


def _windows(text: str, size: int) -> Iterable[tuple[str, ...]]:
    words = _WORD.findall(text.casefold())
    return (tuple(words[index : index + size]) for index in range(len(words) - size + 1))


def _commitment(sentence: str) -> set[str]:
    clean = _MARKER.sub("", sentence)
    if _NEGATION.search(clean):
        return set()
    candidate = {name for name, pattern in _TERMS.items() if pattern.search(clean)}
    if not _DATE.search(clean):
        candidate.discard("delivery")
    return candidate if _PROMISE.search(clean) else set()


def _backed(sentence: str, kinds: set[str], sources: list[str]) -> bool:
    quantities = {
        _normal(match.group())
        for pattern in (_NUMERIC, _DATE)
        for match in pattern.finditer(_MARKER.sub("", sentence))
    }
    for evidence in sources:
        normalized = _normal(evidence.replace("_", " "))
        observed = {
            _normal(match.group())
            for pattern in (_NUMERIC, _DATE)
            for match in pattern.finditer(normalized)
        }
        if (
            _PROMISE.search(normalized)
            and not _NEGATION.search(normalized)
            and quantities <= observed
            and all(_TERMS[kind].search(normalized) for kind in kinds)
        ):
            return True
    return False


class OutputChecks:
    def __init__(self, settings: OutputGuardSettings, prompts: Path) -> None:
        self.settings = settings
        self.private_windows = (
            {
                window
                for prompt in sorted(prompts.glob("*.md"))
                for window in _windows(
                    prompt.read_text(encoding="utf-8"), settings.prompt_word_window
                )
            }
            if settings.prompt_leak
            else set()
        )

    def prompt_leaked(self, answer: str) -> bool:
        return any(
            window in self.private_windows
            for window in _windows(answer, self.settings.prompt_word_window)
        )

    def foreign_pii(
        self, answer: str, allowed_email: str | None, evidence: Iterable[str] = ()
    ) -> bool:
        """Personal data must be the customer's own email or quoted from this turn's evidence.

        Evidence is the cited policy text and the customer's own order data. A store's
        support phone number or email in a cited source is a business contact, not PII.
        """
        allowed = {(match.kind, match.normalized) for text in evidence for match in find_pii(text)}
        if allowed_email:
            allowed.add(("email", allowed_email.casefold()))
        return any(
            match.kind in {"email", "phone", "card"}
            and (match.kind, match.normalized) not in allowed
            for match in find_pii(answer)
        )

    def unbacked_commitment(self, state: ConversationState) -> bool:
        chunks = {chunk.chunk_id: chunk.text for chunk in state.retrieval}
        sources = {str(record.n): chunks.get(record.chunk_id, "") for record in state.citations}
        tracking = (state.order_context or {}).get("get_tracking")
        expected = tracking.get("expected_delivery") if isinstance(tracking, dict) else None
        # The answer renderer appends citations after punctuation, e.g. "Text. [1]".
        # Keep those markers attached to the sentence for the local evidence check.
        cited_answer = re.sub(
            r"([.!?])([ \t]+(?:\[\d+\][ \t]*)+)",
            lambda match: f"{match[2].rstrip()}{match[1]} ",
            state.answer,
        )
        for sentence in answer_sentences(cited_answer):
            cited = [sources[number] for number in _MARKER.findall(sentence) if number in sources]
            for clause in _CLAUSE.split(sentence):
                kinds = _commitment(clause)
                # Only pending requests are possible here. Policy cannot confirm approval.
                if "refund" in kinds and _REFUND_APPROVAL.search(clause):
                    return True
                evidence = cited
                if (
                    kinds == {"delivery"}
                    and isinstance(expected, str)
                    and not _DELIVERY_GUARANTEE.search(clause)
                ):
                    evidence = [*cited, f"expected delivery {expected}"]
                if kinds and not _backed(clause, kinds, evidence):
                    return True
        return False
