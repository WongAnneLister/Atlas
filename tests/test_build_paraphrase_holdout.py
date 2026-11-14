from __future__ import annotations

import json

import pytest
from eval.build_paraphrase_holdout import ParaphraseDraft, build_paraphrases
from eval.schema import Section

from support_agent.config import Settings
from support_agent.data.doc_models import digest

FAQ_Q = "Can I order by phone?"


def sections() -> dict[str, Section]:
    return {
        "orders.maktek_faqs.generic-store.a": Section(
            section_id="orders.maktek_faqs.generic-store.a",
            doc_id="orders",
            text=f"Regarding “{FAQ_Q}”:\n\nNo, we do not take phone orders.",
        ),
        "product.HD928X": Section(
            section_id="product.HD928X",
            doc_id="catalog",
            text="Intro text. For a factory reset press both buttons. Factory note again.",
        ),
    }


def build(families: dict) -> list:
    settings = Settings()
    draft = ParaphraseDraft.model_validate({"families": families})
    return build_paraphrases(
        draft, sections(), [], settings.evaluation, settings.retrieval.store_scope
    )


def test_faq_and_manual_items_store_evidence_strings() -> None:
    faq, manual = build(
        {
            "f": {
                "note": "n",
                "kind": "faq",
                "items": [
                    {
                        "q": "For the generic store: may I phone in an order?",
                        "faq": digest(FAQ_Q)[:12],
                    }
                ],
            },
            "m": {
                "note": "n",
                "kind": "manual",
                "items": [
                    {
                        "q": "How do I reset it?",
                        "product": "HD928X",
                        "anchor": "For a factory reset",
                    }
                ],
            },
        }
    )
    assert faq.gold_sections == ["orders.maktek_faqs.generic-store.a"]
    assert json.loads(faq.notes)["evidence"].startswith("No, we do not")
    assert manual.gold_sections == ["product.HD928X"]
    assert json.loads(manual.notes)["evidence"] == "For a factory reset"


def test_manual_anchor_must_be_unique() -> None:
    with pytest.raises(ValueError, match="exactly once"):
        build(
            {
                "m": {
                    "note": "n",
                    "kind": "manual",
                    "items": [{"q": "Reset?", "product": "HD928X", "anchor": "actory"}],
                }
            }
        )
