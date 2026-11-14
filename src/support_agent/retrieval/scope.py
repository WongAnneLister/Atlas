"""Store scope: keep one store's policy text out of answers about the other store.

The corpus mixes two stores. A question that names exactly one store must not be
answered from the other store's sections, however relevant they look to the reranker.
Sections that belong to no store (the product catalog) stay available to both.
"""

from __future__ import annotations

import re

from support_agent.config import StoreScopeSettings
from support_agent.retrieval.types import RetrievedChunk


def requested_stores(query: str, settings: StoreScopeSettings) -> set[str]:
    return {
        name
        for name, store in settings.stores.items()
        if re.search(store.query_pattern, query, re.IGNORECASE)
    }


def section_store(section_id: str, settings: StoreScopeSettings) -> str | None:
    """The store that owns a section, or None for store-neutral sections."""
    owners = [name for name, store in settings.stores.items() if store.section_marker in section_id]
    if len(owners) > 1:
        raise ValueError(f"Section matches more than one store: {section_id}")
    return owners[0] if owners else None


def scope_chunks(
    query: str, chunks: list[RetrievedChunk], settings: StoreScopeSettings, top_k: int
) -> tuple[list[RetrievedChunk], str | None, int]:
    """Return the top_k chunks allowed for the query, its single store, and the drop count.

    A query that names no store, or several, keeps every chunk.
    """
    stores = requested_stores(query, settings) if settings.enabled else set()
    if len(stores) != 1:
        return chunks[:top_k], None, 0
    (store,) = stores
    kept = [c for c in chunks if section_store(c.section_id, settings) in (store, None)]
    return kept[:top_k], store, len(chunks) - len(kept)
