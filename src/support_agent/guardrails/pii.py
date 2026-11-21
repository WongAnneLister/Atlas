"""Detect common personal data and redact it with typed placeholders."""

import re
from dataclasses import dataclass
from typing import Literal

PIIKind = Literal["email", "phone", "address", "card"]
_WORD_START = r"(?<![\w.+-])"
_NUMBER_END = r"(?![\w-]|\.[0-9])"
_EMAIL = re.compile(
    r"(?<![\w.!#$%&'*+/=?^`{|}~-])[A-Z0-9.!#$%&'*+/=?^`{|}~-]+"
    r"@[A-Z0-9]+(?:-[A-Z0-9]+)*(?:\.[A-Z0-9]+(?:-[A-Z0-9]+)*)*\.[A-Z]{2,}(?![\w-])",
    re.IGNORECASE,
)
_CARD = re.compile(
    _WORD_START + r"(?:[0-9]{13,19}|(?:[0-9]{4}[ -]){4}[0-9]{3}|(?:[0-9]{4}[ -]){3}[0-9]{4,7}"
    r"|[0-9]{4}[ -][0-9]{6}[ -][0-9]{4,5}|(?:[0-9]{4}[ -]){2}[0-9]{5})" + _NUMBER_END
)
_PHONE = re.compile(
    _WORD_START + r"(?:\+(?:(?:[0-9]{1,4}[ .-]){1,4}[0-9]{2,4}|[0-9]{8,15})"
    r"|(?:1[ .-]?)?(?:\([0-9]{3}\)[ .-]?|[0-9]{3}[ .-]?)[0-9]{3}[ .-]?[0-9]{4})" + _NUMBER_END
)
_ADDRESS = re.compile(
    _WORD_START + r"[0-9]{1,6}[A-Z]?[ \t]+(?:[^\W\d_][\w.'\u2019-]*[ \t]+){1,5}"
    r"(?:street|st|road|rd|avenue|ave|boulevard|blvd|drive|dr|lane|ln|court|ct|"
    r"way|place|pl|parkway|pkwy|terrace|ter|circle|cir|trail|trl)\b"
    r"(?:\.?[ \t]+(?:apt\.?|suite|unit|#)[ \t]*[\w-]+)?",
    re.IGNORECASE,
)
_PATTERNS: tuple[tuple[PIIKind, re.Pattern[str]], ...] = (
    ("email", _EMAIL),
    ("card", _CARD),
    ("phone", _PHONE),
    ("address", _ADDRESS),
)


@dataclass(frozen=True)
class PIIMatch:
    kind: PIIKind
    value: str
    normalized: str
    start: int
    end: int


def _luhn(digits: str) -> bool:
    if len(set(digits)) < 2:
        return False
    total = 0
    for index, char in enumerate(reversed(digits)):
        digit = int(char)
        if index % 2:
            digit *= 2
        total += digit - 9 if digit > 9 else digit
    return total % 10 == 0


def _normalize(kind: PIIKind, value: str) -> str | None:
    if kind in {"email", "address"}:
        return " ".join(value.casefold().split())
    digits = re.sub(r"\D", "", value)
    if kind == "card":
        return digits if _luhn(digits) else None
    if not 8 <= len(digits) <= 15:
        return None
    return digits[1:] if len(digits) == 11 and digits.startswith("1") else digits


def find_pii(text: str) -> list[PIIMatch]:
    """Return non-overlapping matches in display order, with normalized values."""
    matches: list[PIIMatch] = []
    for kind, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span()
            if any(start < found.end and found.start < end for found in matches):
                continue
            value = match.group()
            if (normalized := _normalize(kind, value)) is not None:
                matches.append(PIIMatch(kind, value, normalized, start, end))
    return sorted(matches, key=lambda match: match.start)


def redact_pii(text: str) -> str:
    parts: list[str] = []
    cursor = 0
    for match in find_pii(text):
        parts.extend((text[cursor : match.start], f"[{match.kind.upper()}]"))
        cursor = match.end
    parts.append(text[cursor:])
    return "".join(parts)
