"""Routing experiment metrics must not turn no-answer labels into invented intent gold."""

from types import SimpleNamespace

import pytest
from eval import routing_eval
from eval.routing_eval import RoutingItem, RoutingRecord, metrics, validate_pair
from eval.schema import EvalItem

from support_agent.config import Settings
from support_agent.graph.intents import Intent, Path


def row(identity, expected, predicted, failed=False):
    return RoutingRecord(
        item=RoutingItem(
            id=identity,
            text=identity,
            source="fixture",
            group="fixture",
            expected_path=expected,
        ),
        predicted=predicted,
        parse_failed=failed,
        confidence=0.8,
        latency_s=0.1,
    )


def test_metrics_exclude_unlabelled_no_answer_and_keep_failures_in_denominator():
    rows = [
        row("policy", Path.KNOWLEDGE, Intent.POLICY_QUESTION),
        row("fallback", Path.KNOWLEDGE, Intent.CHITCHAT_OTHER, True),
        row("no-answer", None, Intent.POLICY_QUESTION),
    ]
    result = metrics(rows)
    assert result["labelled"] == 2
    assert result["correct"] == 1
    assert result["path_accuracy"] == 0.5
    assert result["failures"] == 1
    assert result["unlabelled_paths"] == {"B": 1}


def test_comparison_requires_identical_questions_labels_and_provenance():
    before = [row("same", Path.KNOWLEDGE, Intent.SHIPPING_DELIVERY)]
    after = [row("same", Path.KNOWLEDGE, Intent.POLICY_QUESTION)]
    meta = {
        "eval_file_hash": "frozen",
        "controls_hash": "fixed",
        "config_hash": "cfg",
        "model": "model",
        "provider": "provider",
    }
    validate_pair(meta, before, meta, after)
    with pytest.raises(ValueError, match="items"):
        validate_pair(meta, before, meta, [row("changed", Path.KNOWLEDGE, Intent.POLICY_QUESTION)])
    with pytest.raises(ValueError, match="config_hash"):
        validate_pair(meta, before, {**meta, "config_hash": "other"}, after)
    with pytest.raises(ValueError, match="duplicate"):
        validate_pair(meta, before * 2, meta, after)


def test_comparison_checks_serialized_items_across_module_instances():
    class ReloadedItem(RoutingItem):
        pass

    before = [row("same", Path.KNOWLEDGE, Intent.SHIPPING_DELIVERY)]
    after = [row("same", Path.KNOWLEDGE, Intent.POLICY_QUESTION)]
    after[0].item = ReloadedItem(**after[0].item.model_dump())
    meta = dict.fromkeys(
        ["eval_file_hash", "controls_hash", "config_hash", "model", "provider"], "fixed"
    )
    validate_pair(meta, before, meta, after)


def test_runner_only_calls_dev_and_controls_and_rejects_changed_prompt(tmp_path, monkeypatch):
    folder = tmp_path / "eval/sets"
    folder.mkdir(parents=True)
    item = EvalItem(
        id="dev-policy",
        group="basic_policy",
        split="dev",
        question="Explain the rules.",
        gold_sections=["policy"],
        answer_points=["rules"],
        answerable=True,
        source="fixture",
    )
    test = item.model_copy(
        update={"id": "held-out", "split": "test", "question": "Never call this."}
    )
    (folder / "eval_v1.jsonl").write_text(
        item.model_dump_json() + "\n" + test.model_dump_json() + "\n"
    )
    controls = tmp_path / "eval/drafts/routing_controls.yaml"
    controls.parent.mkdir()
    controls.write_text('- {id: control, text: "Cancel my order.", expected_path: A}\n')
    prompt = tmp_path / "prompt.md"
    prompt.write_text("First prompt")
    calls = []

    class Classifier:
        def __init__(self, *args):
            self.prompt = ""

        def classify(self, query):
            calls.append((query, self.prompt))
            return SimpleNamespace(
                intent=Intent.POLICY_QUESTION,
                parse_failed=False,
                confidence=0.9,
                error_type=None,
                model_name="fixture",
            )

    monkeypatch.setattr(routing_eval, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(routing_eval, "Classifier", Classifier)
    monkeypatch.setattr(routing_eval, "get_chat_model", lambda *args: None)
    monkeypatch.setattr(routing_eval, "get_settings", Settings)
    monkeypatch.setattr(routing_eval, "source_hash", lambda paths: "fixture")
    monkeypatch.setattr(routing_eval.subprocess, "check_output", lambda *args, **kwargs: "fixture")
    monkeypatch.setattr(routing_eval, "load_dotenv", lambda *args: None)
    args = ["--prompt", str(prompt), "--output", "run.jsonl", "--report", "report.md"]
    routing_eval.main(args)
    routing_eval.main(args)
    assert sorted(calls) == [
        ("Cancel my order.", "First prompt"),
        ("Explain the rules.", "First prompt"),
    ]
    prompt.write_text("Changed prompt")
    with pytest.raises(ValueError, match="provenance"):
        routing_eval.main(args)
