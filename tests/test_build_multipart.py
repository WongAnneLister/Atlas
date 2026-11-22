from __future__ import annotations

import hashlib
from collections import Counter

import pytest
from eval.build_multipart import build_items, dataset_bytes
from eval.common import load_items, load_sections
from eval.registry import load_registry
from eval.schema import EvalItem, MultipartItem, MultipartPart, Section
from pydantic import ValidationError

from support_agent.config import REPO_ROOT, get_settings


def source_items() -> tuple[list[EvalItem], dict[str, Section]]:
    items = []
    sections = {
        name: Section(section_id=name, doc_id=document, text=f"Evidence for {name}")
        for name, document in (("delivery", "a"), ("tracking", "a"), ("payments", "b"))
    }
    for split in ("dev", "test"):
        for index in range(15):
            for name in (*sections, "absent"):
                item_id = f"{split}-{name}-{index}"
                answerable = name in sections
                items.append(
                    EvalItem(
                        id=item_id,
                        group="basic_policy" if answerable else "no_answer",
                        split=split,
                        question=f"What about {name} {index} in {split}?",
                        gold_sections=[name] if answerable else [],
                        answer_points=[sections[name].text] if answerable else [],
                        answerable=answerable,
                        source="fixture",
                    )
                )
    return items, sections


def test_builder_selects_deterministic_pairs_with_frozen_labels() -> None:
    source, sections = source_items()
    source_by_id = {item.id: item for item in source}
    first = build_items(source, sections)
    second = build_items(list(reversed(source)), sections)

    assert dataset_bytes(first) == dataset_bytes(second)
    assert len({item.id for item in first}) == len(first)
    assert len({item.question.casefold() for item in first}) == len(first)
    assert len({frozenset(part.source_item_id for part in item.parts) for item in first}) == len(
        first
    )
    for split in ("dev", "test"):
        assert Counter(item.group for item in first if item.split == split) == {
            "answerable_pair": 20,
            "half_answerable": 20,
            "both_unanswerable": 10,
        }
    for item in first:
        assert item.reviewed is False
        assert ", and also " in item.question
        assert item.question.endswith("?")
        assert item.question.count("?") == 1
        assert len(item.parts) == 2
        left, right = item.parts
        assert left.source_item_id != right.source_item_id
        assert [part.answerable for part in item.parts] == {
            "answerable_pair": [True, True],
            "half_answerable": [True, False],
            "both_unanswerable": [False, False],
        }[item.group]
        if item.group == "answerable_pair":
            assert sections[left.gold_sections[0]].doc_id != sections[right.gold_sections[0]].doc_id
        for part in item.parts:
            original = source_by_id[part.source_item_id]
            assert original.split == item.split
            assert part.text == original.question
            assert part.gold_sections == original.gold_sections
            assert part.answer_points == original.answer_points


def test_builder_refuses_to_fill_quota_with_one_document() -> None:
    source, sections = source_items()
    sections["payments"].doc_id = "a"
    with pytest.raises(ValueError, match=r"dev answerable_pair.*20"):
        build_items(source, sections)


def test_schema_rejects_duplicate_source_parts() -> None:
    part = MultipartPart(
        text="Does this shop ship to Mars?",
        gold_sections=[],
        answer_points=[],
        answerable=False,
        source_item_id="same-source",
    )
    with pytest.raises(ValidationError, match="distinct source"):
        MultipartItem(
            id="example",
            split="test",
            group="both_unanswerable",
            question="Does this shop ship to Mars?",
            source="fixture",
            parts=[part, part],
        )


def test_local_multipart_build_matches_frozen_registry() -> None:
    registry = load_registry()
    source = REPO_ROOT / registry["eval_v1"].path
    settings = get_settings()
    docs = REPO_ROOT / settings.data.processed_dir / "docs"
    if not source.is_file() or not any(docs.glob("*.md")):
        pytest.skip("Frozen local eval_v1 and processed docs are required")
    entry = registry["multipart_v1"]
    content = dataset_bytes(build_items(load_items(source), load_sections(settings)))
    assert hashlib.sha256(content).hexdigest() == entry.sha256
