"""Shared date and category filters for dense, lexical and local retrieval."""

from __future__ import annotations

import json
from collections.abc import Collection
from contextlib import AbstractContextManager, nullcontext
from datetime import date
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from support_agent.config import Settings, get_settings

if TYPE_CHECKING:
    from support_agent.retrieval.chunking import Chunk
    from support_agent.retrieval.types import RetrievedChunk, Retriever


def encode_day(day: date) -> int:
    return day.year * 10000 + day.month * 100 + day.day


def decode_day(value: int) -> date:
    year, rest = divmod(value, 10000)
    month, day = divmod(rest, 100)
    return date(year, month, day)


class RetrievalFilters(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    as_of: date | None = None
    product_category: str | None = None

    def to_expr(self, allowed_categories: Collection[str] | None = None) -> str:
        clauses = []
        if self.as_of is not None:
            day = encode_day(self.as_of)
            clauses.append(f"effective_from_day <= {day} and effective_to_day > {day}")
        if self.product_category is not None:
            if allowed_categories is None:
                allowed_categories = get_settings().retrieval.filters.category_terms
            if self.product_category not in allowed_categories:
                raise ValueError(f"Unknown product category: {self.product_category}")
            category = json.dumps(self.product_category, ensure_ascii=False)
            clauses.append(f'(doc_type == "policy" or product_category == {category})')
        return " and ".join(clauses)

    def matches(self, chunk: Chunk) -> bool:
        if self.as_of is not None and (
            chunk.effective_from is None
            or self.as_of < chunk.effective_from
            or (chunk.effective_to is not None and self.as_of >= chunk.effective_to)
        ):
            return False
        return (
            self.product_category is None
            or chunk.doc_type == "policy"
            or chunk.product_category == self.product_category
        )


def knowledge_filters(question: str, settings: Settings) -> RetrievalFilters | None:
    from support_agent.retrieval.categories import detect_category

    config = settings.retrieval.filters
    if not config.enabled:
        return None
    return RetrievalFilters(
        as_of=settings.orders.today,
        product_category=detect_category(question, settings) if config.category else None,
    )


def supports_filters(source: object) -> bool:
    probe = getattr(source, "supports_filters", None)
    return bool(probe()) if probe is not None else False


def filter_scope(source: object) -> AbstractContextManager[None]:
    scope = getattr(source, "filter_scope", None)
    return scope() if scope is not None else nullcontext()


def retrieve_with_filters(
    retriever: Retriever, query: str, top_k: int, filters: RetrievalFilters | None
) -> tuple[list[RetrievedChunk], bool]:
    if filters is None or (filters.as_of is None and filters.product_category is None):
        return retriever.retrieve(query, top_k), False
    with filter_scope(retriever):
        if supports_filters(retriever):
            return retriever.retrieve(query, top_k, filters=filters), True
        return retriever.retrieve(query, top_k), False
