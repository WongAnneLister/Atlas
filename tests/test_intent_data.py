from __future__ import annotations

from collections import Counter

from eval.intent_data import build_dataset, select_balanced
from eval.intent_records import ExtraDrafts, IntentItem
from eval.schema import EvalItem

from support_agent.config import get_settings
from support_agent.data.intent_map import BITEXT_INTENT_MAP, MAPPING_REASONS
from support_agent.graph.intents import Intent


def test_mapping_covers_real_twenty_seven_source_labels() -> None:
    names = set(
        [
            "cancel_order",
            "change_order",
            "change_shipping_address",
            "check_cancellation_fee",
            "check_invoice",
            "check_payment_methods",
            "check_refund_policy",
            "complaint",
            "contact_customer_service",
            "contact_human_agent",
            "create_account",
            "delete_account",
            "delivery_options",
            "delivery_period",
            "edit_account",
            "get_invoice",
            "get_refund",
            "newsletter_subscription",
            "payment_issue",
            "place_order",
            "recover_password",
            "registration_problems",
            "review",
            "set_up_shipping_address",
            "switch_account",
            "track_order",
            "track_refund",
        ]
    )
    assert set(BITEXT_INTENT_MAP) == names == set(MAPPING_REASONS)
    assert BITEXT_INTENT_MAP["review"] == Intent.CHITCHAT_OTHER
    assert BITEXT_INTENT_MAP["payment_issue"] == Intent.COMPLAINT
    assert all(MAPPING_REASONS.values())


def product(split: str, name: str) -> EvalItem:
    return EvalItem(
        id=name,
        group="model_number",
        split=split,
        question=f"What is the wattage of {name}?",
        gold_sections=[name],
        answer_points=["wattage"],
        answerable=True,
        source="product:fixture",
    )


def test_build_is_deterministic_disjoint_and_has_authored_provenance() -> None:
    settings = get_settings().model_copy(deep=True)
    settings.intent_eval.bitext_holdout_fraction = 0.99
    settings.intent_eval.per_intent = 3
    rows = [
        {"intent": label, "instruction": f"Please help with {label} example {index}"}
        for label in BITEXT_INTENT_MAP
        for index in range(12)
    ]
    rows += [
        dict(rows[0]),
        {"intent": "track_order", "instruction": "Where is my parcel now?"},
        {"intent": "track_order", "instruction": " WHERE is my parcel NOW! "},
        {"intent": "complaint", "instruction": "Where is my parcel now?"},
    ]
    drafts = ExtraDrafts(
        greetings=["Good evening there", "This is a test split product question"],
        returns=["I need a different shirt size", "Can I exchange the unopened headset"],
        returns_source="model:fixture",
    )
    frozen = [product("dev", "dev-model"), product("test", "test-model")]
    frozen.append(
        EvalItem(
            id="colloquial",
            group="colloquial",
            split="dev",
            question="A separate frozen policy question",
            gold_sections=["policy"],
            answer_points=["point"],
            answerable=True,
            source="faq:fixture|bitext:0:cancel_order",
        )
    )
    prompt = 'Example: "Good evening there"'
    first = build_dataset(rows, frozen, drafts, settings, prompt)
    second = build_dataset(list(rows), frozen, drafts, settings, prompt)
    assert first == second
    extras, selected, stats = first
    assert any(i.source == "retrieval_dev:dev-model" for i in extras)
    assert all(i.source != "retrieval_dev:test-model" for i in extras)
    assert all(i.text != "Good evening there" for i in extras)
    assert all(i.text.casefold().strip() != "where is my parcel now?" for i in selected)
    assert all(i.source != "bitext:0:cancel_order" for i in selected)
    assert any(i.source.startswith("model:fixture") for i in extras)
    assert stats["conflicting_texts"] == 1
    assert set(i.intent for i in selected) == set(Intent)
    assert len({i.id for i in selected}) == len(selected)
    assert max(Counter(i.intent for i in selected).values()) <= 3
    settings.intent_eval.per_intent = 1000
    _, full, _ = build_dataset(rows, frozen, drafts, settings, prompt)
    assert all(i.text != rows[0]["instruction"] for i in full)


def test_balanced_sampling_does_not_lose_small_source_buckets() -> None:
    items = [
        IntentItem(
            id=str(i),
            text=f"text {i}",
            intent=Intent.CHITCHAT_OTHER,
            source=f"bitext:{i}",
            source_label="account" if i else "greeting",
        )
        for i in range(100)
    ]
    chosen = select_balanced(items, per_intent=5, seed=42)
    assert len(chosen) == 5
    assert {i.source_label for i in chosen} == {"account", "greeting"}
