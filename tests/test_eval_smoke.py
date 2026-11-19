from collections import Counter

from eval.schema import GROUPS, EvalItem
from eval.smoke import select_smoke


def test_smoke_is_fixed_stratified_and_test_only() -> None:
    rows = [
        EvalItem(
            id=f"{split}-{group}-{index}",
            split=split,
            group=group,
            question="Question",
            gold_sections=[] if group == "no_answer" else ["a", "b"],
            answer_points=[] if group == "no_answer" else ["answer"],
            answerable=group != "no_answer",
            source="fixture",
        )
        for split in ("dev", "test")
        for group in GROUPS
        for index in range(30)
    ]
    smoke = select_smoke(rows, seed=42)
    assert len(smoke) == 70
    assert all(row.split == "test" for row in smoke)
    assert Counter(row.group for row in smoke) == {
        group: 30 if group == "no_answer" else 10 for group in GROUPS
    }
    assert smoke == select_smoke(list(reversed(rows)), seed=42)
