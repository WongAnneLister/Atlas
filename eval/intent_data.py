"""Build a deterministic, source-balanced holdout without changing retrieval gold labels."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import re
from collections import defaultdict

import yaml

from eval.common import load_items, normalised
from eval.intent_inputs import artifact_hashes
from eval.intent_records import ExtraDrafts, IntentItem
from eval.schema import EvalItem
from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.data.doc_models import digest, json_text, write_text
from support_agent.data.intent_map import BITEXT_INTENT_MAP
from support_agent.graph.intents import Intent

log = logging.getLogger(__name__)


def select_balanced(items: list[IntentItem], per_intent: int, seed: int) -> list[IntentItem]:
    rng = random.Random(seed)
    selected: list[IntentItem] = []
    for intent in Intent:
        buckets: dict[str, list[IntentItem]] = defaultdict(list)
        for item in sorted(items, key=lambda i: i.id):
            if item.intent == intent:
                buckets[item.source_label].append(item)
        for label in sorted(buckets):
            rng.shuffle(buckets[label])
        count = 0
        while count < per_intent and any(buckets.values()):
            for label in sorted(buckets):
                if buckets[label] and count < per_intent:
                    selected.append(buckets[label].pop())
                    count += 1
    return selected


def _item(text: str, intent: Intent, source: str, source_label: str) -> IntentItem:
    return IntentItem(
        id=digest(json_text([normalised(text), intent.value])),
        text=text,
        intent=intent,
        source=source,
        source_label=source_label,
    )


def build_dataset(
    rows: list[dict[str, str]],
    frozen: list[EvalItem],
    drafts: ExtraDrafts,
    settings: Settings,
    prompt: str,
) -> tuple[list[IntentItem], list[IntentItem], dict[str, int]]:
    config = settings.intent_eval
    examples = {normalised(s) for s in re.findall(r'"([^"\n]+)"', prompt)}
    excluded = {normalised(i.question) for i in frozen if i.split == "test"} | examples
    used_rows = {
        int(match.group(1))
        for item in frozen
        for match in re.finditer(r"bitext:(\d+):", item.source)
    }
    excluded |= {normalised(rows[index]["instruction"]) for index in used_rows if index < len(rows)}
    extras = [
        _item(i.question, Intent.PRODUCT_QUESTION, "retrieval_dev:" + i.id, "retrieval_product")
        for i in frozen
        if i.split == "dev" and i.group == "model_number"
    ]
    extras += [
        _item(text, Intent.CHITCHAT_OTHER, f"authored:greeting:{index}", "authored_greeting")
        for index, text in enumerate(drafts.greetings)
    ]
    extras += [
        _item(text, Intent.RETURN_EXCHANGE, f"{drafts.returns_source}:{index}", "drafted_return")
        for index, text in enumerate(drafts.returns)
    ]
    candidates: list[IntentItem] = []
    train_rows = 0
    for index, row in enumerate(rows):
        label, text = row["intent"], row["instruction"].strip()
        if label not in BITEXT_INTENT_MAP:
            raise ValueError(f"Unmapped Bitext source label: {label}")
        if index in used_rows or not text or normalised(text) in excluded:
            continue
        partition = int(digest(f"{config.seed}:{normalised(text)}"), 16) / (1 << 256)
        if partition >= config.bitext_holdout_fraction:
            train_rows += 1
            continue
        candidates.append(_item(text, BITEXT_INTENT_MAP[label], f"bitext:{index}:{label}", label))
    candidates += extras
    labels_by_text: dict[str, set[Intent]] = defaultdict(set)
    for item in candidates:
        labels_by_text[normalised(item.text)].add(item.intent)
    conflicts = {text for text, labels in labels_by_text.items() if len(labels) > 1}
    unique: dict[str, IntentItem] = {}
    for item in candidates:
        key = normalised(item.text)
        if key and key not in excluded | conflicts:
            unique.setdefault(key, item)
    extras = [item for item in extras if unique.get(normalised(item.text)) == item]
    selected = select_balanced(list(unique.values()), config.per_intent, config.seed)
    missing = set(Intent) - {item.intent for item in selected}
    if missing:
        raise ValueError("Missing benchmark intents: " + ", ".join(sorted(missing)))
    stats = {
        "raw_bitext_rows": len(rows),
        "reserved_training_rows": train_rows,
        "prior_bitext_rows_excluded": len(used_rows),
        "conflicting_texts": len(conflicts),
        "unique_pool": len(unique),
        "selected": len(selected),
        "extras": len(extras),
    }
    return extras, selected, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = get_settings()
    source = next(s for s in settings.data.sources if s.name == "bitext")
    raw = REPO_ROOT / settings.data.raw_dir / "bitext" / source.files[0]
    with raw.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    folder = REPO_ROOT / settings.evaluation.sets_dir
    frozen = load_items(folder / "eval_v1.jsonl")
    draft_path = REPO_ROOT / settings.intent_eval.extra_drafts
    drafts = ExtraDrafts.model_validate(yaml.safe_load(draft_path.read_text()))
    prompt = (REPO_ROOT / "src/support_agent/graph/prompts/classify.md").read_text()
    extras, selected, stats = build_dataset(rows, frozen, drafts, settings, prompt)
    for name, items in (("intent_extra", extras), ("intent_holdout", selected)):
        write_text(folder / f"{name}.jsonl", "".join(i.model_dump_json() + "\n" for i in items))
    manifest = {
        "stats": stats,
        "split": "intent_holdout",
        "sampling": settings.intent_eval.model_dump(mode="json"),
        "dataset_versions": {s.name: f"{s.repo_id}@{s.revision}" for s in settings.data.sources},
        **artifact_hashes(settings),
        "dataset_hash": digest("".join(i.model_dump_json() + "\n" for i in selected)),
    }
    write_text(folder / "intent_manifest.json", json_text(manifest) + "\n")
    log.info("Built intent holdout: %s", json.dumps(stats, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
