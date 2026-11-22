from datetime import date
from pathlib import Path

import pytest

from support_agent.config import Settings
from support_agent.retrieval.categories import detect_category
from support_agent.retrieval.filters import RetrievalFilters, encode_day
from test_retrieval import item


def test_date_and_category_expressions_and_open_interval_match() -> None:
    start, boundary, later = date(2026, 1, 1), date(2026, 9, 1), date(2026, 11, 9)
    allowed = {"headphones", "hair_dryers"}
    for day in (None, start, date(2026, 8, 31), boundary, later):
        for category in (None, *sorted(allowed)):
            filters = RetrievalFilters(as_of=day, product_category=category)
            expression = filters.to_expr(allowed)
            assert bool(expression) == (day is not None or category is not None)
            for begin, end in ((start, boundary), (boundary, None)):
                for kind, actual in (("policy", ""), ("catalog", "headphones")):
                    row = {
                        "effective_from_day": encode_day(begin),
                        "effective_to_day": encode_day(end) if end is not None else 99991231,
                        "doc_type": kind,
                        "product_category": actual,
                    }
                    chunk = item("x").model_copy(
                        update={
                            "effective_from": begin,
                            "effective_to": end,
                            "doc_type": kind,
                            "product_category": actual,
                        }
                    )
                    assert filters.matches(chunk) == (
                        eval(expression, {"__builtins__": {}}, row) if expression else True
                    )


def test_category_expression_escapes_quotes_and_rejects_unknown_category() -> None:
    filters = RetrievalFilters(product_category='test"\\name')
    assert (
        filters.to_expr({'test"\\name'})
        == r'(doc_type == "policy" or product_category == "test\"\\name")'
    )
    with pytest.raises(ValueError, match="Unknown product category"):
        filters.to_expr({"headphones"})


def test_category_resolves_catalog_codes_and_ignores_ambiguous_matches(tmp_path: Path) -> None:
    settings = Settings()
    settings.data.processed_dir = str(tmp_path)
    catalog = tmp_path / "catalog/products.jsonl"
    catalog.parent.mkdir()
    catalog.write_text(
        '{"model":"BHD340/10"}\n{"model":"TAH4205"}\n{"model":"24E1N1100A"}\n',
        encoding="utf-8",
    )
    assert detect_category("How fast is BHD-340/10?", settings) == "hair_dryers"
    assert detect_category("What are BHD340 specs?", settings) == "hair_dryers"
    assert detect_category("What inputs does 24E1N1100A have?", settings) == "monitors"
    assert detect_category("How long is the headset warranty?", settings) == "headphones"
    assert detect_category("Headphones and BHD340/10?", settings) is None
    assert detect_category("Is TAH99999 in stock?", settings) is None


def test_filter_request_refuses_wrapper_without_probe_before_searching() -> None:
    from support_agent.retrieval.filters import retrieve_with_filters

    calls = []

    class Wrapper:
        def retrieve(self, query, top_k):
            calls.append((query, top_k))
            return [item("current")]

    retriever = Wrapper()
    filters = RetrievalFilters(as_of=date(2026, 9, 1))
    with pytest.raises(TypeError, match=r"Wrapper.*supports_filters"):
        retrieve_with_filters(retriever, "returns", 5, filters)
    assert not calls
    chunks, applied = retrieve_with_filters(retriever, "returns", 5, None)
    assert chunks == [item("current")]
    assert not applied


@pytest.mark.parametrize("capability", [None, 0, "false"])
def test_filter_probe_must_return_an_explicit_boolean(capability) -> None:
    from support_agent.retrieval.filters import supports_filters

    class Store:
        def supports_filters(self):
            return capability

    with pytest.raises(TypeError, match="must return bool"):
        supports_filters(Store())


@pytest.mark.parametrize("declares_support", [False, True])
def test_hybrid_requires_matching_declared_capabilities(declares_support: bool) -> None:
    from support_agent.retrieval.bm25 import Bm25Retriever
    from support_agent.retrieval.dense import DenseRetriever
    from support_agent.retrieval.filters import retrieve_with_filters
    from support_agent.retrieval.hybrid import HybridRetriever
    from test_retrieval import QueryEmbedder, SearchStore

    class LegacyStore(SearchStore):
        def supports_filters(self):
            return False

    class UndeclaredStore(SearchStore):
        supports_filters = None

    class MetadataStore(SearchStore):
        def supports_filters(self):
            return True

    settings = Settings().retrieval
    dense_store = LegacyStore()
    bm25_store = MetadataStore() if declares_support else UndeclaredStore()
    retriever = HybridRetriever(
        DenseRetriever(dense_store, QueryEmbedder()),
        Bm25Retriever(bm25_store, settings),
        settings,
    )
    message = (
        "disagree on filter support" if declares_support else r"UndeclaredStore.*supports_filters"
    )
    with pytest.raises(TypeError, match=message):
        retrieve_with_filters(retriever, "returns", 5, RetrievalFilters(as_of=date(2026, 9, 1)))
    assert not dense_store.calls and not bm25_store.calls


@pytest.mark.parametrize("wrapper", ["refund_cache", "redteam_overlay"])
def test_eval_wrappers_forward_scope_probe_and_date_filter(wrapper: str) -> None:
    from contextlib import contextmanager
    from contextvars import ContextVar

    from eval.redteam_fixtures import OverlayRetriever
    from eval.refund_policy_eval import CachingRetriever

    from support_agent.retrieval.filters import retrieve_with_filters

    events = []
    by_date = RetrievalFilters(as_of=date(2026, 9, 1))

    class Source:
        @contextmanager
        def filter_scope(self):
            events.append("enter")
            try:
                yield
            finally:
                events.append("exit")

        def supports_filters(self):
            events.append("probe")
            return True

        def retrieve(self, query, top_k, filters=None):
            events.append(filters)
            return [item("current")]

    source = Source()
    retriever = (
        CachingRetriever(source)
        if wrapper == "refund_cache"
        else OverlayRetriever(lambda: source, ContextVar("test_eval_turn", default=None))
    )
    chunks, applied = retrieve_with_filters(retriever, "returns", 5, by_date)
    assert applied and chunks == [item("current")]
    assert events == ["enter", "probe", by_date, "exit"]
