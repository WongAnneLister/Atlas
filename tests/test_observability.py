"""Offline checks for optional tracing, trace masking and cost accounting."""

import json
import logging
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from eval.cost_report import cost_by_intent, cost_lines, explanation
from eval.e2e_eval import _priced_run
from eval.e2e_records import E2EMetadata, E2ERecord
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from support_agent.config import CostSettings, ModelPrice, TracingSettings, get_settings
from support_agent.gate.evidence import GateResult
from support_agent.graph.handoff import HandoffPayload, HandoffReason
from support_agent.observability.cost import ModelUsage, UsageLedger, cost_usd
from support_agent.observability.tracing import REDACTED, mask_data, turn_tags
from support_agent.retrieval.types import RetrievedChunk
from test_eval_tools import eval_item

NO_IMPORT = """
import os, sys
os.environ.update({"LANGFUSE_PUBLIC_KEY": KEY, "LANGFUSE_SECRET_KEY": KEY})
from support_agent.config import get_settings
from support_agent.observability import tracing
settings = get_settings()
settings.tracing.enabled = ENABLED
turn = tracing.start_turn(settings, name="t", conversation_id="c", customer_id="u", input_text="hi")
turn.finish({"intent": "policy_question"})
tracing.flush()
assert turn.callbacks == [] and turn.config_metadata == {}
assert "langfuse" not in sys.modules, "langfuse was imported"
"""


@pytest.mark.parametrize(("enabled", "key"), [(False, "set"), (True, "")])
def test_disabled_or_unkeyed_tracing_never_imports_langfuse(enabled: bool, key: str) -> None:
    code = NO_IMPORT.replace("KEY", repr(key)).replace("ENABLED", str(enabled))
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def chunk(number: int) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"chunk-{number}",
        doc_id="returns",
        title="Returns",
        n_tokens=5,
        section_id=f"returns.{number}",
        heading_path="Returns",
        text=f"secret chunk text {number}",
        scores={"rerank": 0.9 - number / 100},
    )


def test_mask_keeps_chunk_ids_and_scores_only() -> None:
    settings = TracingSettings(enabled=True, max_chunks=5)
    masked = mask_data(
        {"retrieval": [chunk(n) for n in range(8)], "rewritten_query": "return window"},
        settings=settings,
    )
    assert len(masked["retrieval"]) == 5
    assert masked["retrieval"][0] == {
        "chunk_id": "chunk-0",
        "section_id": "returns.0",
        "scores": {"rerank": 0.9},
    }
    assert "secret chunk text" not in json.dumps(masked)
    assert masked["rewritten_query"] == "return window"


def test_redaction_removes_customer_text_everywhere() -> None:
    settings = TracingSettings(enabled=True, redact_inputs=True)
    text = "my card 4111 was charged twice"
    state = {
        "messages": [HumanMessage(content=text), AIMessage(content="I will check.")],
        "rewritten_query": text,
        "handoff": {"conversation": [HumanMessage(content=text)]},
    }
    generation_input = [{"role": "user", "content": text}]
    masked = mask_data([state, generation_input], settings=settings)
    dumped = json.dumps(masked)
    assert text not in dumped
    assert REDACTED in dumped
    assert "I will check." in dumped


def test_turn_tags_cover_intent_path_gate_and_handoff() -> None:
    gate = GateResult(score=0.1234, signals={}, passed=False, threshold=0.15, reason="low")
    handoff = HandoffPayload(
        reason=HandoffReason.LOW_EVIDENCE,
        conversation=[],
        rewritten_query="q",
        intent=None,
        created_at=datetime.now(UTC),
    )
    tags, metadata = turn_tags(
        {"intent": "policy_question", "path": "B", "gate": gate, "handoff": handoff}
    )
    assert tags == [
        "intent:policy_question",
        "path:B",
        "gate_passed:false",
        "handoff:low_evidence",
    ]
    assert metadata == {"gate_score": "0.1234"}
    assert turn_tags({}) == ([], {})


def llm_result(model: str | None, usage: dict[str, int] | None) -> LLMResult:
    message = AIMessage(
        content="ok",
        usage_metadata=(
            {**usage, "total_tokens": sum(usage.values())} if usage is not None else None
        ),
        response_metadata={"model_name": model} if model else {},
    )
    return LLMResult(generations=[[ChatGeneration(message=message)]])


def test_ledger_counts_calls_and_tokens_per_reported_model() -> None:
    ledger = UsageLedger()
    ledger.on_llm_end(llm_result("flash", {"input_tokens": 100, "output_tokens": 20}))
    ledger.on_llm_end(llm_result("flash", {"input_tokens": 50, "output_tokens": 10}))
    ledger.on_llm_end(llm_result(None, None))
    assert ledger.by_model["flash"] == ModelUsage(input_tokens=150, output_tokens=30, calls=2)
    assert ledger.by_model["unknown"].calls_without_usage == 1
    assert ledger.calls == 3
    assert ledger.tokens() == (150, 30)
    assert UsageLedger().tokens() == (None, None)


def test_cost_uses_the_price_table_and_never_guesses(caplog: pytest.LogCaptureFixture) -> None:
    prices = CostSettings(
        prices={"flash": ModelPrice(input_per_million_usd=1.0, output_per_million_usd=4.0)}
    )
    usage = {"flash": ModelUsage(input_tokens=1_000_000, output_tokens=500_000, calls=3)}
    assert cost_usd(usage, prices) == pytest.approx(3.0)
    with caplog.at_level(logging.WARNING):
        unknown = cost_usd({"other-model": ModelUsage(input_tokens=10, calls=1)}, prices)
    assert unknown is None
    assert "other-model" in caplog.text
    missing = {"flash": ModelUsage(input_tokens=10, calls=2, calls_without_usage=1)}
    assert cost_usd(missing, prices) is None
    assert cost_usd({}, prices) == 0.0


def measured(item_id: str, intent: str, calls: int, tokens: int, cost: float | None) -> E2ERecord:
    return E2ERecord(
        item=eval_item(item_id),
        intent=intent,
        trace=["rewrite", "classify", intent],
        latency_full_answer_s=0.1,
        llm_calls=calls,
        usage_by_model={"flash": ModelUsage(input_tokens=tokens, calls=calls)},
        estimated_cost_usd=cost,
    )


def fixture_run() -> list[E2ERecord]:
    return [
        measured("p1", "policy_question", 3, 1000, 0.001),
        measured("p2", "policy_question", 3, 3000, 0.003),
        measured("r1", "refund_request", 5, 8000, 0.008),
        measured("c1", "chitchat_other", 2, 0, 0.0),
        E2ERecord(item=eval_item("legacy"), intent="policy_question", latency_full_answer_s=0.1),
    ]


def test_cost_by_intent_aggregates_measured_records() -> None:
    rows = {row.intent: row for row in cost_by_intent(fixture_run())}
    policy = rows["policy_question"]
    assert policy.items == 2  # the legacy record has no per-model usage
    assert policy.mean_calls == 3
    assert policy.mean_tokens == 2000
    assert policy.median_tokens == 2000
    assert policy.mean_cost == pytest.approx(0.002)
    assert policy.token_share == pytest.approx(4000 / 12000)
    assert rows["refund_request"].cost_share == pytest.approx(0.008 / 0.012)
    sentence = explanation(list(rows.values()))
    assert sentence.startswith("`refund_request` costs the most per conversation")
    assert "5.0 LLM calls" in sentence
    assert "4.0x the tokens of `policy_question`" in sentence
    assert "1.7x as many LLM calls; 100% of its tokens are input." in sentence


def test_cost_table_says_when_prices_are_missing() -> None:
    records = [record.model_copy(update={"estimated_cost_usd": None}) for record in fixture_run()]
    text = "\n".join(cost_lines(records))
    assert "Measured items: 4 of 5" in text
    assert "price not set" in text
    assert "`refund_request` uses the most tokens" in text
    assert "`flash` (13 calls)" in text


def test_report_only_prices_a_finished_run(tmp_path: Path, monkeypatch: Any) -> None:
    metadata = E2EMetadata(
        git_sha="sha",
        config_hash="c",
        eval_file_hash="e",
        corpus_hash="k",
        models={"fast": "flash", "main": "flash"},
        dataset_versions={},
        split="test",
        date="2026-11-17",
        customer_id="CUST-0001",
        threshold=0.15,
    )
    run = tmp_path / "run.jsonl"
    rows = [record.model_copy(update={"estimated_cost_usd": None}) for record in fixture_run()]
    run.write_text(
        "\n".join([metadata.model_dump_json(), *[r.model_dump_json() for r in rows]]) + "\n"
    )
    settings = get_settings().model_copy(deep=True)
    settings.costs = CostSettings(
        prices={"flash": ModelPrice(input_per_million_usd=2.0, output_per_million_usd=8.0)}
    )
    loaded, records = _priced_run(run, settings)
    assert loaded == metadata
    assert records[0].estimated_cost_usd == pytest.approx(1000 / 1_000_000 * 2.0)
    assert records[-1].estimated_cost_usd is None


def test_explanation_names_prompt_size_when_calls_match() -> None:
    rows = cost_by_intent(
        [
            measured("p1", "policy_question", 2, 1000, None),
            measured("x1", "product_question", 2, 6000, None),
        ]
    )
    sentence = explanation(rows)
    assert "6.0x the tokens of `policy_question`" in sentence
    assert "The call counts are close, so the gap is prompt size" in sentence
