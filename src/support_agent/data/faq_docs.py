"""FAQ loading, conservative deduplication and cached topic classification."""

from __future__ import annotations

import csv
import json
import logging
import os
import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from support_agent.config import REPO_ROOT, Settings
from support_agent.data.doc_models import (
    FAQ,
    FAQGroup,
    digest,
    normalise,
    numeric_tokens,
    write_text,
)
from support_agent.llm import LLMConfigError, get_chat_model

log = logging.getLogger(__name__)
PROMPT_PATH = REPO_ROOT / "src/support_agent/graph/prompts/faq_topic.md"


def load_faqs(raw_dir: Path) -> list[FAQ]:
    faqs: list[FAQ] = []
    with (raw_dir / "flipkart_faqs/FAQs.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            faqs.append(
                FAQ(
                    source_id=f"flipkart_faqs:{row['question_id']}",
                    dataset="flipkart_faqs",
                    category=normalise(row["parent_category"] + " / " + row["category"]),
                    question=normalise(row["question"]),
                    answer=normalise(row["answer"]),
                )
            )
    path = raw_dir / "maktek_faqs/train_expanded.json"
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if line.strip():
            row = json.loads(line)
            faqs.append(
                FAQ(
                    source_id=f"maktek_faqs:{i:04d}",
                    dataset="maktek_faqs",
                    category="Generic store",
                    question=normalise(row["question"]),
                    answer=normalise(row["answer"]),
                )
            )
    if len({f.source_id for f in faqs}) != len(faqs):
        raise ValueError("Duplicate source FAQ ids")
    return sorted(faqs, key=lambda f: f.source_id)


def deduplicate(
    faqs: list[FAQ],
    threshold: float,
) -> tuple[list[FAQGroup], dict[str, str], dict[str, int]]:
    """Only merge inside one source/category with identical answers.

    Near duplicates also retain every question as context and every source id.
    A changed amount, negation or answer is never silently thrown away.
    """
    groups: list[FAQGroup] = []
    excluded: dict[str, str] = {}
    counts: Counter[str] = Counter()
    exact: dict[str, FAQGroup] = {}
    for faq in faqs:
        if not faq.question or not faq.answer:
            excluded[faq.source_id] = "empty_question_or_answer"
            counts["empty"] += 1
            continue
        key = digest(json.dumps([faq.dataset, faq.category, faq.question, faq.answer]))
        if key in exact:
            exact[key].records.append(faq)
            counts["exact"] += 1
            continue
        match = next((g for g in groups if _near(faq, g.records[0], threshold)), None)
        if match is not None:
            match.records.append(faq)
            exact[key] = match
            counts["near"] += 1
        else:
            group = FAQGroup(records=[faq])
            groups.append(group)
            exact[key] = group
    for reason, count in sorted(counts.items()):
        log.info("dedupe %s: %d", reason, count)
    return groups, excluded, dict(counts)


def _near(faq: FAQ, other: FAQ, threshold: float) -> bool:
    return (
        (faq.dataset, faq.category, faq.answer) == (other.dataset, other.category, other.answer)
        and numeric_tokens(faq.question) == numeric_tokens(other.question)
        and SequenceMatcher(None, faq.question, other.question, autojunk=False).ratio() >= threshold
    )


class TopicDecision(BaseModel):
    key: str
    topic: str
    method: Literal["fast_model", "other_without_model"]
    model: str | None = None


class TopicClassifier:
    def __init__(self, settings: Settings, cache_path: Path) -> None:
        self.settings = settings
        self.path = cache_path
        self.prompt = PROMPT_PATH.read_text(encoding="utf-8")
        self.cache: dict[str, TopicDecision] = {}
        self.methods: Counter[str] = Counter()
        self.models: set[str] = set()
        if cache_path.exists():
            for line in cache_path.read_text(encoding="utf-8").splitlines():
                row = TopicDecision.model_validate_json(line)
                self.cache[row.key] = row

    def classify(self, faq: FAQ) -> str:
        rules = self.settings.data.docs.topic_rules
        for text in (faq.question, faq.category):
            for topic, pattern in rules.items():
                if re.search(pattern, text, re.IGNORECASE):
                    self.methods["rule"] += 1
                    return topic
        # Rules and prompt are part of the key; a changed classifier invalidates old decisions.
        key = digest(self.prompt + json.dumps(rules) + faq.model_dump_json())
        cached = self.cache.get(key)
        if cached is not None:
            if cached.topic not in {*rules, "other"}:
                raise ValueError(f"Invalid cached topic: {cached.topic}")
            self.methods[cached.method] += 1
            if cached.model:
                self.models.add(cached.model)
            return cached.topic
        topic = "other"
        method: Literal["fast_model", "other_without_model"] = "other_without_model"
        model_name = None
        if self.settings.data.docs.classify_leftovers:
            try:
                model = get_chat_model("fast", self.settings)
            except LLMConfigError:
                pass
            else:
                response = model.invoke(
                    [
                        SystemMessage(content=self.prompt),
                        HumanMessage(content=faq.model_dump_json()),
                    ]
                )
                topic = str(response.content).strip()
                if topic not in {*rules, "other"}:
                    raise ValueError(f"Invalid model topic: {topic!r}")
                method = "fast_model"
                model_name = os.environ.get("LLM_FAST_MODEL") or self.settings.llm.fast_model
                if model_name:
                    self.models.add(model_name)
        self.cache[key] = TopicDecision(key=key, topic=topic, method=method, model=model_name)
        self.methods[method] += 1
        return topic

    def save(self) -> None:
        write_text(
            self.path,
            "".join(self.cache[key].model_dump_json() + "\n" for key in sorted(self.cache)),
        )
