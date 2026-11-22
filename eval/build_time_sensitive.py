"""Append deterministic time-sensitive policy cases to the frozen v1 dataset."""

from __future__ import annotations

import hashlib
import re
from datetime import date

from eval.registry import load_registry
from eval.schema import Split, TimeSensitiveItem, TimeSensitivePath
from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.data.policy_versions import VersionedPolicy, load_versions
from support_agent.orders.fixtures import (
    TIME_SENSITIVE_CUSTOMER,
    TIME_SENSITIVE_DEV_ORDERS,
    TIME_SENSITIVE_TEST_ORDERS,
)

SUBJECTS = {"returns": "return window", "refunds": "price adjustment window"}
KNOWLEDGE: dict[Split, tuple[str, ...]] = {
    "dev": (
        "What is the Generic store's {subject} right now?",
        "How many days does the current {subject} at the Generic store allow?",
        "I bought it in August. What is the Generic store's {subject} today?",
        "My purchase was back in August. What is the Generic store's {subject}?",
        "What's the time limit for the Generic store's {subject}?",
        "Where does the Generic store set the current {subject}, in days?",
        "I need the number of days in the Generic store's {subject}.",
        "I ordered in July and want to check the current {subject} at the Generic store.",
        "Even though I shopped last summer, what's the Generic store's {subject} now?",
        "I made my purchase earlier this year. What's the Generic store's {subject} today?",
    ),
    "test": (
        "Can you tell me today's {subject} for the Generic store?",
        "How long is the Generic store's {subject} under its latest policy?",
        "Suppose I bought it in August. What's the current {subject} at the Generic store?",
        "I remember buying it in August. How long is the Generic store's {subject} now?",
        "Under the rules in force today, how many days is the Generic store's {subject}?",
        "How much time do shoppers have under the Generic store's current {subject}?",
        "Could you give me the Generic store's {subject} as it stands today?",
        "I think my purchase was in July. What's today's {subject} at the Generic store?",
        "My receipt is from last summer. What {subject} does the Generic store publish now?",
        "I placed an order earlier this year. How long is the Generic store's {subject} today?",
    ),
}
REFUND_ORDERS: dict[Split, dict[str, date]] = {
    "dev": TIME_SENSITIVE_DEV_ORDERS,
    "test": TIME_SENSITIVE_TEST_ORDERS,
}


def make_item(
    entry: VersionedPolicy,
    split: Split,
    path: TimeSensitivePath,
    question: str,
    as_of: date,
    case_key: str,
    order_id: str | None = None,
) -> TimeSensitiveItem:
    gold = entry.section_at(as_of)
    sentence = entry.old.find if gold == entry.base_section_id else entry.old.replace
    windows = re.findall(r"\b[0-9]+ days\b", sentence)
    if len(windows) != 1:
        raise ValueError(f"Expected one policy window in {entry.base_section_id}")
    topic = entry.base_section_id.split(".", 1)[0]
    return TimeSensitiveItem(
        id=f"ts-{split}-{topic}-{path}-{case_key}",
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
            topic = entry.base_section_id.split(".", 1)[0]
            subject = SUBJECTS[topic]
            if entry.section_at(settings.orders.today) != entry.base_section_id:
                raise ValueError("Configured today must use the current policy")
            items.extend(
                make_item(
                    entry,
                    split,
                    "knowledge",
                    template.format(subject=subject),
                    settings.orders.today,
                    f"current-{index}",
                )
                for index, template in enumerate(templates, start=1)
            )
            if topic == "returns":
                items.extend(
                    make_item(
                        entry,
                        split,
                        "refund",
                        f"What is the return window for Generic store order {order_id}?",
                        order_date,
                        order_id,
                        order_id=order_id,
                    )
                    for order_id, order_date in REFUND_ORDERS[split].items()
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
