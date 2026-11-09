"""Validate labels, source evidence, split counts and cross-split question leakage."""

from __future__ import annotations

import json
import logging
from collections import Counter

from eval.common import (
    load_items,
    load_sections,
    near_duplicate,
    normalised,
    set_hash,
    supported,
    term_present,
)
from eval.schema import GROUPS, Candidate, EvalItem, Section
from support_agent.config import REPO_ROOT, EvalSettings, get_settings
from support_agent.data.doc_models import digest, json_text

log = logging.getLogger(__name__)


def validate_items(
    items: list[EvalItem],
    sections: dict[str, Section],
    config: EvalSettings,
    *,
    counts: bool = True,
) -> list[str]:
    errors: list[str] = []
    ids: set[str] = set()
    questions: set[str] = set()
    if counts:
        totals = Counter((item.group, item.split) for item in items)
        for group in GROUPS:
            for split, expected in (
                ("dev", config.dev_per_group),
                ("test", config.per_group - config.dev_per_group),
            ):
                if totals[group, split] != expected:
                    errors.append(f"{group}/{split}: {totals[group, split]}, expected {expected}")
    for item in items:
        if item.id in ids:
            errors.append(f"Duplicate id: {item.id}")
        ids.add(item.id)
        question = normalised(item.question)
        if question in questions:
            errors.append(f"Duplicate question: {item.id}")
        questions.add(question)
        missing = set(item.gold_sections) - sections.keys()
        if missing:
            errors.append(f"{item.id}: missing sections {sorted(missing)}")
            continue
        gold = [sections[sid] for sid in item.gold_sections]
        if item.group == "cross_doc" and len({section.doc_id for section in gold}) < 2:
            errors.append(f"{item.id}: cross_doc needs different documents")
        for point in item.answer_points:
            if not any(supported(point, section.text, config.phrase_overlap) for section in gold):
                errors.append(f"{item.id}: unsupported answer point {point!r}")
        for section in gold:
            if not any(
                supported(point, section.text, config.phrase_overlap)
                for point in item.answer_points
            ):
                errors.append(f"{item.id}: unused gold section {section.section_id}")
    dev = [item for item in items if item.split == "dev"]
    test = [item for item in items if item.split == "test"]
    for left in dev:
        for right in test:
            if near_duplicate(left.question, right.question, config):
                errors.append(f"Dev/test near-duplicate: {left.id} / {right.id}")
    return errors


def validate_current() -> list[str]:
    settings = get_settings()
    folder = REPO_ROOT / settings.evaluation.sets_dir
    items = load_items(folder / "eval_v1.jsonl")
    sections = load_sections(settings)
    errors = validate_items(items, sections, settings.evaluation)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest["set_hash"] != set_hash(items):
        errors.append("Frozen questions or labels changed")
    if manifest["corpus_hash"] != digest(json_text([s.model_dump() for s in sections.values()])):
        errors.append("Corpus changed since eval labels were frozen")
    candidates = [
        Candidate.model_validate_json(line)
        for line in (folder / "candidates.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    by_id = {candidate.item.id: candidate for candidate in candidates}
    corpus = "\n".join(section.text for section in sections.values())
    for item in items:
        if item.group != "no_answer":
            continue
        draft = by_id.get(item.id)
        if draft is None or not draft.key_terms:
            errors.append(f"{item.id}: no absent-topic key terms")
        elif any(
            term_present(term, corpus) or not term_present(term, item.question)
            for term in draft.key_terms
        ):
            errors.append(f"{item.id}: absent-topic filter no longer holds")
    return errors


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        errors = validate_current()
    except (OSError, ValueError) as exc:
        log.error("eval validation failed: %s", exc)
        return 1
    for error in errors:
        log.error("%s", error)
    log.info("validation failures: %d", len(errors))
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
