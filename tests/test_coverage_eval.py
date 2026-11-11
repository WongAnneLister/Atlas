"""Offline safeguards for frozen coverage experiments."""

import json

import pytest
from eval import coverage_eval
from eval.coverage_compare import paired_lines
from eval.coverage_inputs import load_inputs

from support_agent.config import Settings
from support_agent.gate.evidence import GateResult


def test_frozen_inputs_reject_duplicate_ids_and_do_not_mix_test_with_dev(tmp_path):
    path = tmp_path / "inputs.jsonl"
    case = {
        "id": "one",
        "split": "dev",
        "subset": "controls",
        "scenario": "full",
        "question": "Question?",
        "complete": True,
        "chunks": [],
    }
    held_out = {**case, "id": "hidden", "split": "test"}
    path.write_text(
        json.dumps({"fixture": True})
        + "\n"
        + "\n".join(json.dumps(r) for r in [case, held_out])
        + "\n"
    )
    _, items = load_inputs(path, "dev")
    assert [i.id for i in items] == ["one"]
    path.write_text(
        json.dumps({"fixture": True})
        + "\n"
        + "\n".join(json.dumps(r) for r in [case, case, held_out])
        + "\n"
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_inputs(path, "dev")


def test_runner_resumes_failures_and_rejects_changed_prompt(tmp_path, monkeypatch):
    path = tmp_path / "inputs.jsonl"
    case = {
        "id": "one",
        "split": "dev",
        "subset": "controls",
        "scenario": "absent",
        "question": "Question?",
        "complete": False,
        "chunks": [],
    }
    path.write_text(json.dumps({"fixture": True}) + "\n" + json.dumps(case) + "\n")
    prompt = tmp_path / "src/support_agent/graph/prompts/answer.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("Original prompt")
    calls = []

    class FakePath:
        def __init__(self, deps):
            pass

        def gate(self, state):
            return {
                "gate": GateResult(
                    score=1, signals={}, passed=True, threshold=0.17, reason="passed"
                )
            }

        def answer(self, state):
            calls.append(state.rewritten_query)
            return {
                "answer": "handoff",
                "handoff": {"reason": "answer_error"},
                "answer_status": "model_error",
                "answer_error_type": "ConnectionError",
            }

    monkeypatch.setattr(coverage_eval, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(coverage_eval, "get_settings", Settings)
    monkeypatch.setattr(coverage_eval, "KnowledgePath", FakePath)
    monkeypatch.setattr(coverage_eval, "source_hash", lambda paths: "fixture")
    monkeypatch.setattr(coverage_eval, "load_dotenv", lambda *args: None)
    monkeypatch.setattr(coverage_eval.subprocess, "check_output", lambda *args, **kwargs: "fixture")
    args = ["--inputs", str(path), "--output", "run.jsonl", "--report", "report.md"]
    coverage_eval.main(args)
    coverage_eval.main(args)
    assert calls == ["Question?"]
    record = json.loads((tmp_path / "run.jsonl").read_text().splitlines()[1])
    assert record["status"] == "model_error"
    prompt.write_text("Changed prompt")
    with pytest.raises(ValueError, match="provenance"):
        coverage_eval.main(args)
    coverage_eval.main([*args, "--report-only"])
    assert calls == ["Question?"]
    run = tmp_path / "run.jsonl"
    original = run.read_text()
    run.write_text(original + original.splitlines()[1] + "\n")
    with pytest.raises(ValueError, match="duplicate"):
        coverage_eval.main([*args, "--report-only"])
    run.write_text(original.splitlines()[0] + "\n")
    with pytest.raises(ValueError, match="complete"):
        coverage_eval.main([*args, "--report-only"])


def test_legacy_fixture_preserves_cited_partial_answer_acceptance():
    from eval.legacy_knowledge import LegacyKnowledgePath
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    from support_agent.graph.deps import GraphDeps
    from support_agent.graph.state import ConversationState
    from test_graph_knowledge import evidence

    with GraphDeps(
        Settings(),
        main_model=FakeListChatModel(
            responses=["Returns are allowed within 30 days [1]. Refund timing is not stated."]
        ),
    ) as deps:
        path = LegacyKnowledgePath(deps)
        state = ConversationState(
            rewritten_query="Return window and refund timing?", retrieval=evidence(0.99)
        )
        state = state.model_copy(update=path.gate(state))
        result = path.answer(state)
    assert result["answer_status"] == "answered"
    assert result.get("handoff") is None


def test_paired_report_rejects_changed_inputs_and_counts_all_failures(tmp_path):
    meta = {
        k: "fixed"
        for k in (
            "inputs_hash",
            "config_hash",
            "split",
            "provider",
            "main_model",
            "model_options",
            "runtime",
            "git_sha",
            "prompt_hash",
            "code_hash",
            "date",
        )
    }
    row = coverage_eval.CoverageRecord(
        case={
            "id": "one",
            "split": "dev",
            "subset": "controls",
            "scenario": "absent",
            "question": "Question?",
            "complete": False,
            "chunks": [],
        },
        accepted=True,
        answer="unsupported",
        status="answered",
        error_type=None,
        latency_s=1,
    )
    path = tmp_path / "before.jsonl"
    path.write_text(json.dumps(meta) + "\n" + row.model_dump_json() + "\n")
    failed = row.model_copy(update={"accepted": False, "status": "model_error"})
    text = "\n".join(paired_lines(meta, [failed], path))
    assert "| Original | controls | 100.00% |" in text
    assert "| Candidate | controls | 0.00% |" in text
    with pytest.raises(ValueError, match="inputs_hash"):
        paired_lines({**meta, "inputs_hash": "changed"}, [failed], path)


def test_report_does_not_invent_false_accept_measurement_without_negative_cases(tmp_path):
    row = coverage_eval.CoverageRecord(
        case={
            "id": "supported",
            "split": "dev",
            "subset": "retrieval_dev",
            "scenario": "full",
            "question": "Question?",
            "complete": True,
            "chunks": [],
        },
        accepted=True,
        answer="Answer",
        status="answered",
        error_type=None,
        latency_s=1,
    )
    path = tmp_path / "report.md"
    coverage_eval.report(path, {}, [row])
    assert "| retrieval_dev | 1 | n/a | 0.00% |" in path.read_text()
