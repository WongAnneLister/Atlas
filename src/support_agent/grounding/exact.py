"""Check that literal quantities and model identifiers occur in cited evidence."""

import re
import unicodedata
from collections.abc import Iterator, Sequence
from decimal import Decimal

from support_agent.grounding.split import CITATION
from support_agent.retrieval.bm25 import normalise_model_numbers

_CURRENCIES = {
    r"us\s*\$": "USD",
    r"usd(?:\s*\$)?": "USD",
    "us dollars?": "USD",
    "€": "EUR",
    "eur": "EUR",
    "euros?": "EUR",
    "£": "GBP",
    "gbp": "GBP",
    "₹": "INR",
    "inr": "INR",
    r"rs\.?": "INR",
    "rupees?": "INR",
    r"ca?\s*\$": "CAD",
    r"cad(?:\s*\$)?": "CAD",
    r"au?\s*\$": "AUD",
    r"aud(?:\s*\$)?": "AUD",
    r"nz\s*\$": "NZD",
    r"nzd(?:\s*\$)?": "NZD",
    r"\$": "USD",
}
_UNITS = {
    "business[- ]+days?": "business_day",
    "working[- ]+days?": "business_day",
    "calendar[- ]+days?": "calendar_day",
    "days?": "day",
    "weeks?": "week",
    "months?": "month",
    "years?": "year",
    "hours?|hrs?|h": "hour",
    "minutes?|mins?": "minute",
    "seconds?|secs?": "second",
    "percent(?:age)?[- ]+points?|pp": "percentage_point",
    "%|percent(?:age)?": "percent",
    "kilograms?|kg": "kg",
    "grams?|g": "g",
    "pounds?|lbs?": "lb",
    "millimet(?:er|re)s?|mm": "mm",
    "centimet(?:er|re)s?|cm": "cm",
    "met(?:er|re)s?|m": "m",
    "inches?|inch": "inch",
    "lit(?:er|re)s?|l": "L",
    "millilit(?:er|re)s?|ml": "mL",
    "watts?|w": "W",
    "kilowatts?|kw": "kW",
    "volts?|v": "V",
    "gigahertz|ghz": "GHz",
    "megahertz|mhz": "MHz",
    "hertz|hz": "Hz",
}

_CURRENCY = "|".join(_CURRENCIES)
_UNIT = "|".join(_UNITS)
_INTEGER = r"(?:\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})+,\d{3}|\d+)"
_MAGNITUDE = rf"(?:{_INTEGER}(?:\.\d+)?|\.\d+)"
_NUMBER = rf"[+-]?{_MAGNITUDE}"
_TOKENS = re.compile(
    rf"(?<!\w)(?P<sign>[+-])?(?P<currency>{_CURRENCY})\s*"
    rf"(?P<amount>(?(sign)|[+-]?){_MAGNITUDE})(?!\w|[.,]\d)"
    rf"|(?<!\w)(?<!\d[.,])(?P<number>{_NUMBER})(?:[\s-]*(?P<suffix>{_CURRENCY}|{_UNIT}))?"
    r"(?!\w|[.,]\d)"
    r"|\b(?P<model>[a-z][a-z0-9/-]*\d[a-z0-9/-]*)\b",
    re.IGNORECASE,
)
_DASHES = str.maketrans("\u2212\u2010\u2011", "---")
LiteralKey = tuple[str, Decimal | str]


def _alias(value: str, choices: dict[str, str]) -> str | None:
    return next(
        (
            canonical
            for spelling, canonical in choices.items()
            if re.fullmatch(spelling, value, re.IGNORECASE)
        ),
        None,
    )


def _literals(text: str) -> Iterator[tuple[LiteralKey, str]]:
    normalized = unicodedata.normalize("NFKC", CITATION.sub(" ", text)).translate(_DASHES)
    for token in _TOKENS.finditer(normalized):
        if model := token["model"]:
            yield ("model", normalise_model_numbers(model)), model
            continue
        currency = token["currency"] or token["suffix"] or ""
        unit = _alias(currency, _CURRENCIES) or _alias(currency, _UNITS) or "number"
        number = (token["sign"] or "") + (token["amount"] or token["number"])
        value = Decimal(number.replace(",", ""))
        yield (unit, value), token.group()


def missing_literals(text: str, evidence: Sequence[str]) -> tuple[str, ...]:
    """Return unsupported literals in claim order. Literal matches do not prove entailment."""
    observed = {key for chunk in evidence for key, _ in _literals(chunk)}
    missing: dict[LiteralKey, str] = {}
    for key, surface in _literals(text):
        if key not in observed:
            missing.setdefault(key, surface)
    return tuple(missing.values())
