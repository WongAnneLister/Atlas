from __future__ import annotations

import pytest
from eval.build_store_controls import ControlDraft, build_controls, faq_index
from eval.schema import Section

from support_agent.config import Settings
from support_agent.data.doc_models import digest

QUESTION = "Can I cancel my order?"
TEXT = f"Regarding “{QUESTION}”:\n\nYes, before it ships."


def sections() -> dict[str, Section]:
    return {
        sid: Section(section_id=sid, doc_id="orders", text=TEXT)
        for sid in ("orders.maktek_faqs.generic-store.a", "orders.flipkart_faqs.order.b")
    }


def draft(question: str) -> ControlDraft:
    item = {"q": question, "faq": digest(QUESTION)[:12]}
    return ControlDraft.model_validate({"families": {"fam": {"note": "n", "items": [item]}}})


def build(question: str) -> list:
    settings = Settings()
    return build_controls(
        draft(question), sections(), [], settings.evaluation, settings.retrieval.store_scope
    )


def test_faq_index_finds_every_section_with_the_question() -> None:
    assert len(faq_index(sections())[digest(QUESTION)[:12]]) == 2


def test_gold_is_limited_to_the_named_store() -> None:
    [item] = build("For the generic store: can my order be called off?")
    assert item.gold_sections == ["orders.maktek_faqs.generic-store.a"]
    assert item.answer_points == ["Yes, before it ships."]
    assert item.answerable
    assert '"route_ok": false' in item.notes


@pytest.mark.parametrize("question", ["Can my order be called off?", "Flipkart or generic store?"])
def test_questions_must_name_exactly_one_store(question: str) -> None:
    with pytest.raises(ValueError, match="exactly one store"):
        build(question)
