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
