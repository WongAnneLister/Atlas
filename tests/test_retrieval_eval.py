from eval.retrieval_eval import result_snapshot, select_items
from eval.schema import EvalItem

from test_retrieval_experiment import metadata, question


def test_default_test_also_evaluates_dev_but_never_no_answer() -> None:
    dev = question()
    test = dev.model_copy(update={"id": "test", "split": "test"})
    absent = EvalItem(
        id="absent",
        group="no_answer",
        split="test",
        question="absent?",
        answerable=False,
        gold_sections=[],
        answer_points=[],
        source="fixture",
    )
    assert select_items([test, absent, dev], "test") == [dev, test]
    assert select_items([test, absent, dev], "all") == [dev, test]
    assert select_items([test, absent, dev], "dev") == [dev]


def test_dependency_version_changes_invalidate_retrieval_cache_snapshot() -> None:
    meta = metadata()
    original = result_snapshot("execution", meta)
    meta.runtime["torch"] = "a different version"
    assert result_snapshot("execution", meta) != original
