import pytest
from eval.metrics import hit_all_at_k, mrr, recall_at_k


def test_section_recall_counts_unique_gold_but_duplicate_chunks_consume_slots() -> None:
    ranked = ["noise", "a", "a", "b"]
    assert recall_at_k(ranked, ["a", "b"], 1) == 0
    assert recall_at_k(ranked, ["a", "b"], 3) == 0.5
    assert recall_at_k(ranked, ["a", "b"], 5) == 1
    assert mrr(ranked, ["a", "b"]) == 0.5
    assert not hit_all_at_k(ranked, ["a", "b"], 3)
    assert hit_all_at_k(ranked, ["a", "b"], 5)


def test_missing_gold_empty_rankings_and_no_gold() -> None:
    for ranked, gold in [([], ["a"]), (["noise"], ["a"]), (["a"], [])]:
        assert recall_at_k(ranked, gold, 5) == 0
        assert mrr(ranked, gold) == 0
        assert not hit_all_at_k(ranked, gold, 5)


def test_metrics_reject_invalid_cutoffs() -> None:
    with pytest.raises(ValueError):
        recall_at_k(["a"], ["a"], 0)
    with pytest.raises(ValueError):
        hit_all_at_k(["a"], ["a"], -1)
