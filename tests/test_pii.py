"""Offline checks for private-data detection and logging and trace masking."""

import io
import logging

import pytest
from langchain_core.messages import AIMessage

from support_agent.config import TracingSettings
from support_agent.observability.tracing import mask_data


@pytest.mark.parametrize(
    ("value", "kind", "normalized", "placeholder"),
    [
        ("Fictional.User@example.com", "email", "fictional.user@example.com", "[EMAIL]"),
        ("(202) 555-0142", "phone", "2025550142", "[PHONE]"),
        ("+44 20 7946 0958", "phone", "442079460958", "[PHONE]"),
        ("21 Mockingbird Lane", "address", "21 mockingbird lane", "[ADDRESS]"),
        ("4111 1111 1111 1111", "card", "4111111111111111", "[CARD]"),
    ],
)
def test_redact_pii_is_typed(value: str, kind: str, normalized: str, placeholder: str) -> None:
    from support_agent.guardrails.pii import find_pii, redact_pii

    text = f"Fixture: {value}."
    (match,) = find_pii(text)
    assert (match.kind, match.normalized) == (kind, normalized)
    assert text[match.start : match.end] == match.value == value
    assert redact_pii(text) == f"Fixture: {placeholder}."


def test_redaction_preserves_ids_models_prices_dates_and_invalid_card() -> None:
    from support_agent.guardrails.pii import redact_pii

    text = "ORD-000001 BHD340/10 RT-1234567890 $123.45 2026-11-21 4111 1111 1111 1112"
    assert redact_pii(text) == text


def test_logging_filter_redacts_interpolated_arguments_and_exception() -> None:
    from support_agent.observability.logging import PIIRedactionFilter

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(PIIRedactionFilter())
    logger = logging.Logger("pii-fixture")
    logger.addHandler(handler)
    try:
        raise ValueError("Contact fictional@example.com")
    except ValueError:
        logger.exception("Card: %s", "4111 1111 1111 1111")
    recorded = stream.getvalue()
    assert "Card: [CARD]" in recorded
    assert "ValueError: Contact [EMAIL]" in recorded
    assert "fictional@example.com" not in recorded
    assert "4111" not in recorded


def test_langfuse_redacts_kept_nested_strings_and_keeps_existing_chunk_mask() -> None:
    source = {
        "messages": [AIMessage(content="Email fictional@example.com.")],
        "metadata": {"fictional@example.com": "Pickup: 21 Mockingbird Lane"},
        "retrieval": [
            {"chunk_id": "chunk-1", "section_id": "sec.1", "scores": {"rerank": 0.8}, "text": "x"},
        ],
    }
    result = mask_data(source, settings=TracingSettings(enabled=True, redact_inputs=False))
    assert result["messages"][0]["content"] == "Email [EMAIL]."
    assert result["metadata"] == {"[EMAIL]": "Pickup: [ADDRESS]"}
    assert result["retrieval"] == [
        {"chunk_id": "chunk-1", "section_id": "sec.1", "scores": {"rerank": 0.8}},
    ]
