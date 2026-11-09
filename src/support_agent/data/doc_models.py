"""Typed source records and document-build artifacts, all local-only."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

from pydantic import BaseModel, Field


class FAQ(BaseModel):
    source_id: str
    dataset: str
    category: str
    question: str
    answer: str


class FAQGroup(BaseModel):
    records: list[FAQ]


class Product(BaseModel):
    product_id: str
    model: str
    name: str
    attributes: dict[str, str]
    description: str
    source_id: str


class BuildIndex(BaseModel):
    built_at: str
    input_hash: str
    config_hash: str
    assignments: dict[str, str] = Field(default_factory=dict)
    excluded: dict[str, str] = Field(default_factory=dict)
    dedupe_counts: dict[str, int] = Field(default_factory=dict)
    topic_methods: dict[str, int] = Field(default_factory=dict)
    topic_models: list[str] = Field(default_factory=list)


class DocumentHeader(BaseModel):
    doc_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_datasets: list[str]
    built_at: str = Field(min_length=1)


class DocumentStats(BaseModel):
    doc_id: str
    sections: int
    words: int


class ValidationSummary(BaseModel):
    documents: list[DocumentStats]
    source_faqs: int
    covered_faqs: int
    coverage: float
    products: int
    sections: int
    excluded: dict[str, str]
    dedupe_counts: dict[str, int]
    topic_methods: dict[str, int]


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "br", "div", "li", "td", "tr"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "div", "li", "td", "tr"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def normalise(text: str) -> str:
    parser = _HTMLText()
    parser.feed(text)
    return " ".join(unicodedata.normalize("NFKC", "".join(parser.parts)).split())


def numeric_tokens(text: str) -> set[str]:
    """Keep decimals, signs and units; 30 days cannot become 30 percent."""
    pattern = r"[+-]?\d+(?:[.,]\d+)*(?:\s*(?:%|days?|hours?|weeks?|months?|years?|₹|Rs\.?))?"
    return set(re.findall(pattern, text))


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
