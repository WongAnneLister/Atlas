"""Multi-turn and memory evals refuse to report when model calls failed (no models called)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from eval import context_ab, context_eval, memory_long_eval, memory_short_eval
from eval.run_health import INVALID_RUN_STATUS, invalid_arms_message, transcript_error
from eval.sim.models import ConversationTranscript, SimTurn
from langchain_core.messages import AIMessage, HumanMessage

from support_agent.config import Settings
from support_agent.memory.long_term.policy import extract_memory_candidates
from support_agent.memory.short_term.facts import PinnedFacts
from test_sim import _sample_scenario


def _chat(error: str | None = None, *, http: str | None = None) -> ConversationTranscript:
    return ConversationTranscript(
        scenario_id="sim-test-1",
        category="topic_switch",
        customer_id="CUST-0001",
        turns=[SimTurn(turn_index=1, user_message="hi", dependency_error=error, error_type=http)],
    )


class _Closable:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def close(self) -> None:
        pass


def _no_models(module: Any, monkeypatch: pytest.MonkeyPatch, chats: list[Any]) -> None:
    async def fake_suite(*args: Any, **kwargs: Any) -> list[ConversationTranscript]:
        return chats

    monkeypatch.setattr(module, "load_scenarios", lambda path: [_sample_scenario(nightly=True)])
    monkeypatch.setattr(module, "build_simulator_model", lambda settings: (None, "fake-sim"))
    monkeypatch.setattr(module, "OrderService", _Closable)
    monkeypatch.setattr(module, "GraphDeps", _Closable)
    monkeypatch.setattr(module, "run_suite", fake_suite)


def test_one_dead_arm_is_refused_even_when_the_pooled_rate_passes() -> None:
    arms = {"healthy": [_chat()] * 20, "dead": [_chat("APIStatusError")] + [_chat()] * 9}
    message = invalid_arms_message(arms)
    assert message is not None and message.startswith("arm dead:")
    assert invalid_arms_message({"healthy": [_chat()] * 20}) is None


def test_http_and_session_failures_count_as_errors() -> None:
    assert transcript_error(_chat(http="http_500")) == "http_500"
    empty = ConversationTranscript(
        scenario_id="s", category="topic_switch", customer_id="CUST-0001", stop_reason="error"
    )
    assert transcript_error(empty) == "session_error"
    assert transcript_error(_chat()) is None


def test_memory_short_writes_no_report_when_model_calls_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_models(memory_short_eval, monkeypatch, [_chat("APIStatusError")])
    report = tmp_path / "memory_short.md"
    status = memory_short_eval.main(["--report", str(report), "--run-root", str(tmp_path / "runs")])
    assert status == INVALID_RUN_STATUS
    assert not report.exists()
    [run_dir] = (tmp_path / "runs").iterdir()
    assert (run_dir / "items.jsonl").exists() and not (run_dir / "metrics.json").exists()


def test_context_eval_writes_no_report_when_model_calls_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_models(context_eval, monkeypatch, [_chat("APIStatusError")])
    report = tmp_path / "context.md"
    status = context_eval.main(
        ["--report", str(report), "--run-root", str(tmp_path / "runs"), "--repeats", "1"]
    )
    assert status == INVALID_RUN_STATUS
    assert not report.exists()


def test_context_ab_writes_no_report_or_chart_when_one_arm_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_models(context_ab, monkeypatch, [])

    def fake_arm(base: Any, scenarios: Any, *, strategy: str, **kwargs: Any) -> Any:
        dead = strategy == "chunked" and kwargs.get("chunk_turns") is None
        return {}, [_chat("APIStatusError" if dead else None)]

    monkeypatch.setattr(context_ab, "_run_arm", fake_arm)
    report, chart = tmp_path / "context_ab.md", tmp_path / "chart.png"
    status = context_ab.main(
        ["--report", str(report), "--chart", str(chart), "--run-root", str(tmp_path / "runs")]
    )
    assert status == INVALID_RUN_STATUS
    assert not report.exists() and not chart.exists()


def test_memory_long_writes_no_report_when_model_calls_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Deps(_Closable):
        def knowledge_retriever(self) -> Any:
            return type("R", (), {"retrieve": lambda self, query, k: []})()

    def dead(scenario: Any, arm: str, settings: Any, retriever: Any) -> Any:
        return memory_long_eval.ScenarioResult(
            scenario_id=scenario.scenario_id,
            group=scenario.group,
            arm=arm,  # type: ignore[arg-type]
            latency_ms=1.0,
            fact_used=None,
            memory_loaded=None,
            redundant_question=None,
            stale_error=None,
            leaked=None,
            deletion_honoured=None,
            stored_memories=[],
            storage_bytes=0,
            answer_preview="",
            dependency_error="memory_extraction:APIStatusError" if arm == "memory_on" else None,
        )

    monkeypatch.setattr(memory_long_eval, "GraphDeps", _Deps)
    monkeypatch.setattr(memory_long_eval, "_run_one", dead)
    report, csv = tmp_path / "memory_long.md", tmp_path / "review.csv"
    argv = ["x", "--report", str(report), "--review-csv", str(csv)]
    monkeypatch.setattr(sys, "argv", [*argv, "--run-root", str(tmp_path / "runs")])
    assert memory_long_eval.main() == INVALID_RUN_STATUS
    assert not report.exists() and not csv.exists()


def test_strict_memory_extraction_raises_instead_of_storing_nothing() -> None:
    class _DeadModels:
        def structured(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("Insufficient Balance")

    class _Builder:
        def build(self, *args: Any, **kwargs: Any) -> list[Any]:
            return []

    kwargs: dict[str, Any] = {
        "pinned_facts": PinnedFacts(),
        "compacted_blocks": [],
        "messages": [HumanMessage(content="I am vegan"), AIMessage(content="Noted.")],
        "models": _DeadModels(),
        "builder": _Builder(),
        "settings": Settings().memory.long_term,
    }
    assert extract_memory_candidates(**kwargs) == []
    with pytest.raises(RuntimeError, match="Insufficient Balance"):
        extract_memory_candidates(**kwargs, strict=True)


def test_simulator_retries_a_dropped_connection_instead_of_crashing_the_run() -> None:
    import httpx
    from eval.sim.user import UserSimulator
    from langchain_core.messages import AIMessage as Reply

    from support_agent.reliability.settings import RetrySettings

    class _Flaky:
        calls = 0

        def invoke(self, messages: Any) -> Reply:
            self.calls += 1
            if self.calls == 1:
                raise httpx.ConnectError("Connection error.")
            return Reply(content="Where is my order?")

    policy = RetrySettings(
        max_attempts=3, base_delay_s=0, max_delay_s=0, jitter_ratio=0, budget_s=5
    )
    model = _Flaky()
    simulator = UserSimulator(model, model_name="flaky", prompt="p", retry=policy)  # type: ignore[arg-type]
    reply = simulator.next_turn(_sample_scenario(), [], 1)
    assert reply.text == "Where is my order?" and model.calls == 2
    with pytest.raises(httpx.ConnectError):
        UserSimulator(_Flaky(), model_name="flaky", prompt="p").next_turn(  # type: ignore[arg-type]
            _sample_scenario(), [], 1
        )
