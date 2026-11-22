"""Build the local multipart benchmark from the frozen eval_v1 questions."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from itertools import combinations, product
from random import Random

from eval.common import load_items, load_sections
from eval.registry import file_hash, load_registry
from eval.schema import EvalItem, MultipartGroup, MultipartItem, MultipartPart, Section, Split
from support_agent.config import REPO_ROOT, get_settings
from support_agent.data.doc_models import digest

SEED = 24
QUOTAS: dict[MultipartGroup, int] = {
    "answerable_pair": 20,
    "half_answerable": 20,
    "both_unanswerable": 10,
}
SPLITS: tuple[Split, ...] = ("dev", "test")
SOURCE_GROUPS = ("basic_policy", "model_number")


def make_part(item: EvalItem) -> MultipartPart:
    return MultipartPart(
        text=item.question,
        gold_sections=item.gold_sections,
        answer_points=item.answer_points,
        answerable=item.answerable,
        source_item_id=item.id,
    )


def make_item(
    split: Split, group: MultipartGroup, left: EvalItem, right: EvalItem
) -> MultipartItem:
    pair_id = digest(f"{left.id}\n{right.id}")
    left_text = left.question.rstrip(".!?")
    right_text = right.question.rstrip(".!?")
    return MultipartItem(
        id=f"mp-{split}-{group}-{pair_id}",
        split=split,
        group=group,
        question=f"{left_text}, and also {right_text}?",
        source="eval_v1:multipart_template",
        parts=[make_part(left), make_part(right)],
    )


def build_items(source: Sequence[EvalItem], sections: dict[str, Section]) -> list[MultipartItem]:
    if len({item.id for item in source}) != len(source):
        raise ValueError("eval_v1 contains duplicate source item IDs")

    ordered = sorted(source, key=lambda item: item.id)
    items: list[MultipartItem] = []
    for split in SPLITS:
        # Colloquial prefixes can add a request beyond their labelled FAQ.
        answerable = [
            item
            for item in ordered
            if item.split == split and item.group in SOURCE_GROUPS and len(item.gold_sections) == 1
        ]
        absent = [item for item in ordered if item.split == split and item.group == "no_answer"]
        doc_by_item: dict[str, str] = {}
        for item in answerable:
            section = item.gold_sections[0]
            if section not in sections:
                raise ValueError(f"Missing gold section {section} for {item.id}")
            doc_by_item[item.id] = sections[section].doc_id
        candidates: dict[MultipartGroup, list[tuple[EvalItem, EvalItem]]] = {
            "answerable_pair": [
                (left, right)
                for left, right in combinations(answerable, 2)
                if doc_by_item[left.id] != doc_by_item[right.id]
            ],
            "half_answerable": list(product(answerable, absent)),
            "both_unanswerable": list(combinations(absent, 2)),
        }
        for group, quota in QUOTAS.items():
            pairs = candidates[group]
            if len(pairs) < quota:
                raise ValueError(f"{split} {group} requires {quota} pairs, found {len(pairs)}")
            rng = Random(f"{SEED}:{split}:{group}")
            selected = rng.sample(pairs, quota)
            if group == "half_answerable":
                for index in rng.sample(range(quota), quota // 2):
                    left, right = selected[index]
                    selected[index] = right, left
            items.extend(make_item(split, group, left, right) for left, right in selected)
    return items


def dataset_bytes(items: Sequence[MultipartItem]) -> bytes:
    return "".join(item.model_dump_json() + "\n" for item in items).encode("utf-8")


def main() -> None:
    registry = load_registry()
    v1 = registry["eval_v1"]
    source = REPO_ROOT / v1.path
    if file_hash(source) != v1.sha256:
        raise ValueError("eval_v1 differs from its frozen registry entry")
    multipart = registry["multipart_v1"]
    data = dataset_bytes(build_items(load_items(source), load_sections(get_settings())))
    if hashlib.sha256(data).hexdigest() != multipart.sha256:
        raise ValueError("Generated multipart_v1 differs from its frozen registry entry")
    (REPO_ROOT / multipart.path).write_bytes(data)


if __name__ == "__main__":
    main()
