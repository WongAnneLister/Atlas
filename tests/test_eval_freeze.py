from __future__ import annotations

from pathlib import Path

import pytest
from eval.build_set import build
from eval.common import save_items, set_hash
from eval.schema import GROUPS, EvalItem, Section

from support_agent.config import Settings, get_settings
from support_agent.data.doc_models import digest, json_text


@pytest.fixture
def frozen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Settings, Path]:
    settings = get_settings().model_copy(deep=True)
    settings.evaluation.sets_dir = str(tmp_path)
    settings.evaluation.per_group = 2
    settings.evaluation.dev_per_group = 1
    sections = {
        "r": Section(section_id="r", doc_id="returns", text="Returns within 30 days."),
        "p": Section(section_id="p", doc_id="payments", text="Coupon codes expire."),
    }
    subjects = [
        "orchid",
        "volcano",
        "pyramid",
        "whale",
        "mushroom",
        "nebula",
        "waterfall",
        "diamond",
        "mangrove",
        "satellite",
    ]
    items = []
    for index, group in enumerate(GROUPS):
        for offset, split in enumerate(["dev", "test"]):
            gold = [] if group == "no_answer" else ["r"]
            points = [] if group == "no_answer" else ["Returns within 30 days."]
            if group == "cross_doc":
                gold, points = ["r", "p"], ["Returns within 30 days.", "Coupon codes expire."]
            items.append(
                EvalItem(
                    id=f"{group}-{split}",
                    group=group,
                    split=split,
                    question=subjects[index * 2 + offset],
                    gold_sections=gold,
                    answer_points=points,
                    answerable=group != "no_answer",
                    source="fixture",
                    reviewed=index == 0,
                )
            )
    output = tmp_path / "eval_v1.jsonl"
    save_items(output, items)
    metadata = {"fixture": "pinned"}
    (tmp_path / "manifest.json").write_text(
        json_text(
            {
                "input_fingerprint": digest(json_text(metadata)),
                "set_hash": set_hash(items),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("eval.build_set.input_metadata", lambda _: metadata)
    monkeypatch.setattr("eval.build_set.load_sections", lambda _: sections)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("A frozen set must never be redrafted")

    monkeypatch.setattr("eval.build_set.faq_candidates", forbidden)
    return settings, output


def test_frozen_rebuild_preserves_bytes_and_review_flags(frozen: tuple[Settings, Path]) -> None:
    settings, path = frozen
    before = path.read_bytes()
    assert build(settings) == path
    assert path.read_bytes() == before


@pytest.mark.parametrize("change", ["labels", "inputs"])
def test_frozen_rebuild_rejects_changed_labels_or_inputs(
    frozen: tuple[Settings, Path],
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    settings, path = frozen
    if change == "labels":
        path.write_text(
            path.read_text(encoding="utf-8").replace("30 days", "60 days"),
            encoding="utf-8",
        )
    else:
        monkeypatch.setattr("eval.build_set.input_metadata", lambda _: {"fixture": "changed"})
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Frozen eval inputs/labels changed"):
        build(settings)
    assert path.read_bytes() == before
