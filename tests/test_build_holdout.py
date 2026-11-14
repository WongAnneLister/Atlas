from __future__ import annotations

import json

import pytest
from eval.build_holdout import Draft, build_items, item_id, phrase_present, scope_sections
from eval.schema import EvalItem, Section

from support_agent.config import get_settings


def sections() -> dict[str, Section]:
    return {
        "payments.flipkart_faqs.payment.x": Section(
            section_id="payments.flipkart_faqs.payment.x",
            doc_id="payments",
            text="Pay with Visa or MasterCard. Others may apply.",
        ),
        "payments.maktek_faqs.generic-store.y": Section(
            section_id="payments.maktek_faqs.generic-store.y",
            doc_id="payments",
            text="We accept major credit cards, debit cards, and PayPal.",
        ),
        "product.BHD340/10": Section(
            section_id="product.BHD340/10", doc_id="catalog", text="Wattage: 2100 W"
        ),
    }


def draft(*items: dict[str, object], closed_list: bool = False) -> Draft:
    return Draft.model_validate(
        {"families": {"fam": {"note": "n", "closed_list": closed_list, "items": list(items)}}}
    )


def test_phrase_match_uses_whole_words() -> None:
    assert not phrase_present("Rs.", "Others. may apply")
    assert phrase_present("paypal", "and PayPal.")


def test_scopes_select_store_and_product_sections() -> None:
    assert scope_sections("generic", sections()) == ["payments.maktek_faqs.generic-store.y"]
    assert scope_sections("flipkart", sections()) == ["payments.flipkart_faqs.payment.x"]
    assert scope_sections("product:BHD340/10", sections()) == ["product.BHD340/10"]
    with pytest.raises(ValueError, match="no sections"):
        scope_sections("product:BHD999/10", sections())
    with pytest.raises(ValueError, match="Unknown"):
        scope_sections("store", sections())


def test_build_rejects_phrase_present_in_scope() -> None:
    bad = draft(
        {
            "q": "For the generic store: Can I pay with PayPal?",
            "scope": "generic",
            "absent": ["PayPal"],
        }
    )
    with pytest.raises(ValueError, match="phrase present"):
        build_items(bad, sections(), [], get_settings().evaluation)


def test_build_allows_phrase_present_only_in_other_scope() -> None:
    good = draft(
        {"q": "For Flipkart: Can I pay with PayPal?", "scope": "flipkart", "absent": ["PayPal"]},
        closed_list=True,
    )
    [item] = build_items(good, sections(), [], get_settings().evaluation)
    assert item.id == item_id(item.question)
    assert (item.group, item.split, item.answerable) == ("no_answer", "test", False)
    assert json.loads(item.notes)["closed_list"] is True
    assert item.source == "holdout:near_miss_v1:fam"


def test_build_rejects_near_duplicates_of_existing_questions() -> None:
    existing = EvalItem(
        id="old",
        group="no_answer",
        split="test",
        question="For Flipkart: Can I pay with Venmo?",
        gold_sections=[],
        answer_points=[],
        answerable=False,
        source="fixture",
    )
    dup = draft(
        {"q": "For Flipkart: can I pay with Venmo?", "scope": "flipkart", "absent": ["Venmo"]}
    )
    with pytest.raises(ValueError, match="near duplicate"):
        build_items(dup, sections(), [existing], get_settings().evaluation)
