from __future__ import annotations

import pytest

from support_agent.config import Settings, StoreScopeSettings
from support_agent.retrieval.scope import requested_stores, scope_chunks, section_store
from support_agent.retrieval.types import RetrievedChunk


def chunk(section_id: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=section_id,
        doc_id="d",
        section_id=section_id,
        title="t",
        heading_path="h",
        text="text",
        n_tokens=1,
        scores={"rerank": 0.5},
    )


FLIPKART = chunk("payments.flipkart_faqs.payment.a")
GENERIC = chunk("payments.maktek_faqs.generic-store.b")
PRODUCT = chunk("product.BHD340/10")


def settings() -> StoreScopeSettings:
    return Settings().retrieval.store_scope


def test_requested_stores_matches_whole_names_case_insensitively() -> None:
    assert requested_stores("For Flipkart: can I pay?", settings()) == {"flipkart"}
    assert requested_stores("for the GENERIC STORE: can I pay?", settings()) == {"generic"}
    assert requested_stores("Can I pay with cash?", settings()) == set()
    assert requested_stores("Flipkart or the generic store?", settings()) == {
        "flipkart",
        "generic",
    }


def test_section_store_marks_product_catalog_as_neutral() -> None:
    assert section_store(FLIPKART.section_id, settings()) == "flipkart"
    assert section_store(GENERIC.section_id, settings()) == "generic"
    assert section_store(PRODUCT.section_id, settings()) is None


def test_single_store_query_drops_only_the_other_store() -> None:
    chunks = [FLIPKART, PRODUCT, GENERIC]
    kept, store, dropped = scope_chunks("For the generic store: refunds?", chunks, settings(), 5)
    assert (store, dropped) == ("generic", 1)
    assert kept == [PRODUCT, GENERIC]


def test_unscoped_ambiguous_or_disabled_queries_keep_ranked_order() -> None:
    chunks = [FLIPKART, GENERIC, PRODUCT]
    assert scope_chunks("Refunds?", chunks, settings(), 2) == ([FLIPKART, GENERIC], None, 0)
    both = "Flipkart or the generic store: refunds?"
    assert scope_chunks(both, chunks, settings(), 5)[0] == chunks
    off = settings().model_copy(update={"enabled": False})
    assert scope_chunks("For Flipkart: refunds?", chunks, off, 5)[0] == chunks


def test_filter_truncates_after_dropping() -> None:
    chunks = [FLIPKART] * 6 + [GENERIC, GENERIC]
    kept, _, dropped = scope_chunks("For the generic store: refunds?", chunks, settings(), 5)
    assert kept == [GENERIC, GENERIC]
    assert dropped == 6


def test_section_matching_two_stores_is_an_error() -> None:
    clash = chunk("x.flipkart_faqs.maktek_faqs.y")
    with pytest.raises(ValueError, match="more than one store"):
        section_store(clash.section_id, settings())
