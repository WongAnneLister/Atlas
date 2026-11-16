from __future__ import annotations

import pytest
from pydantic import ValidationError

from support_agent.config import GateSettings, Settings
from support_agent.gate.evidence import evaluate
from support_agent.gate.signals import (
    entity_terms,
    good_count,
    key_hit,
    margin,
    specific_terms,
    top_score,
)
from support_agent.retrieval.types import RetrievedChunk


def chunk(chunk_id: str, text: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        doc_id="doc",
        section_id=chunk_id,
        title="Support policy",
        heading_path="Support policy > Returns",
        text=text,
        n_tokens=3,
        scores={"rerank": score},
    )


def legacy_gate() -> GateSettings:
    """The round-two gate: neutral key_hit, no entity terms, no veto."""
    return Settings().gate.model_copy(
        update={
            "key_hit_without_terms": "neutral",
            "entity_terms": False,
            "require_specific_term_hit": False,
        }
    )


def test_gate_signals_cover_scores_empty_lists_and_configured_terms() -> None:
    settings = legacy_gate()
    chunks = [
        chunk("one", "Return window is 30 days for model BHD340/10", 0.9),
        chunk("two", "Refund requests need the original receipt", 0.7),
    ]
    assert top_score(chunks) == pytest.approx(0.9)
    assert good_count(chunks, settings) == pytest.approx(2 / 3)
    assert margin(chunks) == pytest.approx(0.2)
    assert key_hit("Can I return BHD-340/10 in 30 days?", chunks, settings) == 1
    assert (
        key_hit("Does the $50 coupon expire?", [chunk("three", "$50 coupon", 0.8)], settings) == 1
    )
    assert key_hit("What do you think?", chunks, settings) == 1
    assert top_score([]) == 0
    assert good_count([], settings) == 0
    assert margin([]) == 0
    assert evaluate("What do you think?", [], settings, allow_untuned=True).passed is False


def test_gate_requires_explicit_untuned_opt_in_and_returns_reason() -> None:
    settings = Settings().gate.model_copy(update={"threshold": None})
    with pytest.raises(ValueError, match="threshold is unset"):
        evaluate("return", [chunk("one", "Return policy", 0.9)], settings)
    result = evaluate("return", [chunk("one", "Return policy", 0.9)], settings, allow_untuned=True)
    assert result.threshold == settings.untuned_threshold
    assert result.passed
    assert result.reason == "passed"


def test_gate_rejects_weights_that_do_not_sum_to_one() -> None:
    settings = Settings().model_dump()
    settings["gate"]["weights"]["top_score"] = 0.9
    with pytest.raises(ValidationError, match=r"sum to 1\.0"):
        Settings.model_validate(settings)


def test_key_hit_without_terms_adds_no_free_score() -> None:
    """Regression: a neutral 1.0 gave every term-free no-answer query 0.15 for free."""
    settings = Settings().gate.model_copy(update={"key_hit_without_terms": "exclude"})
    weak = [
        chunk("one", "Gift wrapping is available at checkout", 0.01),
        chunk("two", "Orders ship in 3 days", 0.005),
    ]
    assert key_hit("What do you think?", weak, settings) is None
    result = evaluate("What do you think?", weak, settings, allow_untuned=True)
    assert "key_hit" not in result.signals
    assert result.score < 0.02
    legacy = evaluate("What do you think?", weak, legacy_gate(), allow_untuned=True)
    assert legacy.score >= 0.15


def test_exclusion_renormalises_and_matches_legacy_when_terms_exist() -> None:
    settings = Settings().gate
    chunks = [chunk("one", "Refund requests take 7 days", 0.9), chunk("two", "Other", 0.2)]
    query = "How long does a refund take?"
    assert evaluate(query, chunks, settings, allow_untuned=True).score == pytest.approx(
        evaluate(query, chunks, legacy_gate(), allow_untuned=True).score
    )


def test_named_entity_absent_from_evidence_vetoes_the_gate() -> None:
    """Regression: a related payment section passed for an unlisted payment brand."""
    settings = Settings().gate
    payments = [chunk("one", "We accept major credit cards, debit cards, and PayPal.", 0.9)]
    query = "Can I use Cash App Pay to pay for a purchase at this store?"
    assert specific_terms(query, settings) == ["cash app pay"]
    result = evaluate(query, payments, settings, allow_untuned=True)
    assert not result.passed
    assert result.reason == "key_terms_absent"
    assert evaluate(query, payments, legacy_gate(), allow_untuned=True).passed


def test_veto_needs_only_one_named_term_in_evidence() -> None:
    settings = Settings().gate
    evidence = [chunk("one", "BHD340/10 has a 14 mm nozzle", 0.9)]
    query = "I mean BHD340/10, rather than BHD510/03. What is its nozzle width?"
    assert evaluate(query, evidence, settings, allow_untuned=True).passed


def test_entity_terms_skip_sentence_openers_scope_terms_and_stopwords() -> None:
    settings = Settings().gate
    assert entity_terms("Explain the return rules.", settings) == []
    assert entity_terms("For Flipkart: What is SuperCoin Pay?", settings) == ["supercoin pay"]
    assert entity_terms("For Flipkart, How quickly can I pay with PhonePe?", settings) == [
        "phonepe"
    ]
    assert entity_terms("can i pay with venmo", settings) == []


def test_entity_terms_are_off_in_legacy_mode() -> None:
    assert specific_terms("Can I pay with Venmo?", legacy_gate()) == []


def test_another_named_term_does_not_stand_in_for_a_missing_model_number() -> None:
    """Regression: TAH5206 (absent) passed because "USB" hit in the TAH6206 manual."""
    settings = Settings().gate.model_copy(update={"require_model_number_hit": True})
    manual = [chunk("one", "TAH6206 What's in the box: USB dongle, USB-C cable", 0.45)]
    query = "Do the TAH5206 headphones come with a USB dongle?"
    loose = settings.model_copy(update={"require_model_number_hit": False})
    assert evaluate(query, manual, loose, allow_untuned=True).passed
    result = evaluate(query, manual, settings, allow_untuned=True)
    assert not result.passed
    assert result.reason == "model_number_absent"


def test_model_veto_needs_one_named_model_and_ignores_model_free_queries() -> None:
    settings = Settings().gate.model_copy(update={"require_model_number_hit": True})
    evidence = [chunk("one", "BHD340/10 has a 14 mm nozzle", 0.9)]
    query = "I mean BHD340/10, rather than BHD510/03. What is its nozzle width?"
    assert evaluate(query, evidence, settings, allow_untuned=True).passed
    refund = [chunk("one", "Refund requests take 7 days", 0.9)]
    assert evaluate("How long does a refund take?", refund, settings, allow_untuned=True).passed
