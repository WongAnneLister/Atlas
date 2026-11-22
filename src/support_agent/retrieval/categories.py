"""Recognize unambiguous catalog categories from model codes and query words."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

from support_agent.config import REPO_ROOT, Settings
from support_agent.gate.signals import model_terms


@lru_cache(maxsize=1)
def _catalog_index(
    path: Path, *, stamp: int, categories: tuple[tuple[str, str], ...]
) -> Mapping[str, set[str]]:
    del stamp  # The file stamp is part of the cache key.
    known: dict[str, set[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        model = json.loads(line)["model"]
        matched = next(
            (category for prefix, category in categories if model.startswith(prefix)),
            dict(categories)["monitor"],
        )
        for code in _catalog_codes(model):
            # A question may use the family code without the catalog's regional suffix.
            for alias in (code, code.split()[0]):
                known.setdefault(alias, set()).add(matched)
    return known


def _words(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold()))


def _catalog_codes(text: str) -> list[str]:
    # Philips monitor codes start with digits, outside the gate's model pattern.
    monitors = re.findall(r"\b\d+[a-z][a-z0-9]*(?:[-/][a-z0-9]+)*\b", text, re.I)
    return [*model_terms(text), *(_words(code) for code in monitors)]


def detect_category(question: str, settings: Settings) -> str | None:
    terms = settings.retrieval.filters.category_terms
    words = f" {_words(question)} "
    matched = {
        category
        for category, phrases in terms.items()
        if any(f" {_words(phrase)} " in words for phrase in phrases)
    }
    codes = _catalog_codes(question)
    if codes:
        path = REPO_ROOT / settings.data.processed_dir / "catalog/products.jsonl"
        try:
            stamp = path.stat().st_mtime_ns
        except FileNotFoundError:
            pass
        else:
            index = _catalog_index(
                path, stamp=stamp, categories=tuple(settings.data.docs.product_categories.items())
            )
            for code in codes:
                matched.update(index.get(code, set()) & terms.keys())
    return next(iter(matched)) if len(matched) == 1 else None
