from types import SimpleNamespace

import eval.intent_eval as intent_eval
import pytest
from eval.intent_eval import measure
from eval.intent_records import IntentItem, IntentRecord, IntentRun
from eval.intent_report import confusion_matrix, intent_metrics, write_report

from support_agent.graph.intents import Intent


def test_runtime_metadata_tolerates_missing_optional_provider(monkeypatch) -> None:
    from importlib.metadata import PackageNotFoundError

    def installed(name):
        if name == "langchain-deepseek":
            raise PackageNotFoundError(name)
        return "fixture-version"

    monkeypatch.setattr(intent_eval, "version", installed)
    runtime = intent_eval.runtime_versions()
    assert "langchain-deepseek" not in runtime
    assert runtime["langgraph"] == "fixture-version"


def record(gold, predicted, identity="fixture") -> IntentRecord:
    return IntentRecord(
        item=IntentItem(
            id=identity, text=identity, intent=gold, source="fixture", source_label="fixture"
        ),
        predicted=predicted,
        confidence=0.8,
        parse_failed=False,
        latency_s=1.0,
        provenance="snapshot",
    )


def test_metrics_distinguish_wrong_intent_from_wrong_path() -> None:
    records = [
        record(Intent.ORDER_STATUS, Intent.SHIPPING_DELIVERY, "a"),
        record(Intent.POLICY_QUESTION, Intent.PRODUCT_QUESTION, "b"),
        record(Intent.REFUND_REQUEST, Intent.POLICY_QUESTION, "c"),
        record(Intent.COMPLAINT, Intent.COMPLAINT, "d"),
    ]
    values = intent_metrics(records)
    assert values["accuracy"] == 0.25
    assert values["path_accuracy"] == 0.75
    assert values["per_intent"][Intent.COMPLAINT]["precision"] == 1
    assert values["per_intent"][Intent.ORDER_STATUS]["recall"] == 0
    labels, matrix = confusion_matrix(records)
    assert sum(map(sum, matrix)) == 4
    assert matrix[labels.index("refund_request")][labels.index("policy_question")] == 1


def test_prediction_cache_keeps_original_latency_and_rejects_mismatched_item(tmp_path) -> None:
    calls = []

    class Classifier:
        def classify(self, query):
            calls.append(query)
            return SimpleNamespace(
                intent=Intent.ORDER_STATUS,
                confidence=0.9,
                parse_failed=False,
                error_type=None,
                model_name="fake-model",
            )

    item = record(Intent.ORDER_STATUS, Intent.ORDER_STATUS).item
    first = measure(item, Classifier(), tmp_path, "snapshot")
    second = measure(item, Classifier(), tmp_path, "snapshot")
    assert len(calls) == 1
    assert second.cache_hit
    assert second.latency_s == first.latency_s
    with pytest.raises(ValueError, match="provenance"):
        measure(
            item.model_copy(update={"text": "changed question"}), Classifier(), tmp_path, "snapshot"
        )
    measure(item, Classifier(), tmp_path, "different-model-snapshot")
    assert len(calls) == 2


def test_report_has_full_provenance_and_confusion_matrix_without_question_text(tmp_path) -> None:
    row = record(Intent.ORDER_STATUS, Intent.SHIPPING_DELIVERY)
    row.item.text = "Source text must remain local"
    meta = {
        "git_sha": "base-sha",
        "code_hash": "code-hash",
        "config_hash": "config-hash",
        "prompt_hash": "prompt-hash",
        "dataset_hash": "dataset-hash",
        "date": "fixture-date",
        "model": "fake-model",
        "provider": "fake-provider",
        "dataset_versions": {"bitext": "fixed-revision"},
        "target_accuracy": 0.9,
        "sample_stats": {},
        "response_models": ["fake-model"],
        "model_options": {},
    }
    path = tmp_path / "intent.md"
    write_report(IntentRun(metadata=meta, records=[row]), path)
    text = path.read_text()
    for value in ("base-sha", "config-hash", "prompt-hash", "dataset-hash", "fixed-revision"):
        assert value in text
    assert "Confusion matrix" in text
    assert "Path accuracy" in text
    assert row.item.text not in text
