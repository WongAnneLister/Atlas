"""Append deterministic time-sensitive policy cases to the frozen v1 dataset."""

from __future__ import annotations

import hashlib
import re
from datetime import date

from eval.registry import load_registry
from eval.schema import Split, TimeSensitiveItem, TimeSensitivePath
from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.data.policy_versions import VersionedPolicy, load_versions
from support_agent.orders.fixtures import TIME_SENSITIVE_CUSTOMER, TIME_SENSITIVE_ORDER_DATES

SUBJECTS = {"returns": "return window", "refunds": "price adjustment window"}
KNOWLEDGE: dict[Split, tuple[str, ...]] = {
    "dev": (
        "What is the Generic store's {subject} right now?",
        "How many days does the current {subject} at the Generic store allow?",
        "I bought it in August. What is the Generic store's {subject} today?",
        "My purchase was back in August. What is the Generic store's {subject}?",
    ),
    "test": (
        "Can you tell me today's {subject} for the Generic store?",
        "How long is the Generic store's {subject} under its latest policy?",
        "Suppose I bought it in August. What's the current {subject} at the Generic store?",
        "I remember buying it in August. How long is the Generic store's {subject} now?",
    ),
}
REFUND: dict[Split, tuple[str, ...]] = {
    "dev": (
        "For my Generic store order {order_id}, what {subject} applies?",
        "Please check the {subject} for Generic store order {order_id}.",
    ),
    "test": (
        "How long was the {subject} when I placed Generic store order {order_id}?",
        "I need help with Generic store order {order_id}. Which {subject} covers it?",
    ),
}


def make_item(
    entry: VersionedPolicy,
    split: Split,
    path: TimeSensitivePath,
    question: str,
    as_of: date,
    index: int,
    order_id: str | None = None,
) -> TimeSensitiveItem:
    gold = entry.section_at(as_of)
    sentence = entry.old.find if gold == entry.base_section_id else entry.old.replace
    windows = re.findall(r"\b[0-9]+ days\b", sentence)
    if len(windows) != 1:
        raise ValueError(f"Expected one policy window in {entry.base_section_id}")
    topic = entry.base_section_id.split(".", 1)[0]
    return TimeSensitiveItem(
        id=f"ts-{split}-{topic}-{path}-{order_id or 'current'}-{index}",
        split=split,
        path=path,
        question=question,
        as_of=as_of,
        version_of=entry.base_section_id,
        order_id=order_id,
        customer_id=TIME_SENSITIVE_CUSTOMER.customer_id if order_id else None,
        gold_sections=[gold],
        answer_points=windows,
        answerable=True,
        source="synthetic_template",
    )


def build_items(settings: Settings) -> list[TimeSensitiveItem]:
    versions = load_versions(settings.policy_versions)
    items = []
    for split, templates in KNOWLEDGE.items():
        for entry in versions.entries:
            subject = SUBJECTS[entry.base_section_id.split(".", 1)[0]]
            if entry.section_at(settings.orders.today) != entry.base_section_id:
                raise ValueError("Configured today must use the current policy")
            items.extend(
                make_item(
                    entry,
                    split,
                    "knowledge",
                    template.format(subject=subject),
                    settings.orders.today,
                    index,
                )
                for index, template in enumerate(templates, start=1)
            )
            for order_id, order_date in TIME_SENSITIVE_ORDER_DATES.items():
                items.extend(
                    make_item(
                        entry,
                        split,
                        "refund",
                        template.format(subject=subject, order_id=order_id),
                        order_date,
                        index,
                        order_id,
                    )
                    for index, template in enumerate(REFUND[split], start=1)
                )
    return items


def extend_dataset(frozen: bytes, items: list[TimeSensitiveItem]) -> bytes:
    if not frozen.endswith(b"\n"):
        raise ValueError("Expected the frozen dataset to end with a newline")
    return frozen + "".join(
        item.model_dump_json(exclude_none=True) + "\n" for item in items
    ).encode("utf-8")


def main() -> None:
    registry = load_registry()
    v1 = registry["eval_v1"]
    frozen = (REPO_ROOT / v1.path).read_bytes()
    if hashlib.sha256(frozen).hexdigest() != v1.sha256:
        raise ValueError("eval_v1 differs from its frozen registry entry")
    v2 = registry["eval_v2"]
    data = extend_dataset(frozen, build_items(get_settings()))
    if hashlib.sha256(data).hexdigest() != v2.sha256:
        raise ValueError("Generated eval_v2 differs from its frozen registry entry")
    (REPO_ROOT / v2.path).write_bytes(data)


if __name__ == "__main__":
    main()
