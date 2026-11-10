from __future__ import annotations

import pytest
from pydantic import ValidationError

from support_agent.config import Settings
from support_agent.gate.evidence import evaluate
from support_agent.gate.signals import good_count, key_hit, margin, top_score
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


def test_gate_signals_cover_scores_empty_lists_and_configured_terms() -> None:
    settings = Settings().gate
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
