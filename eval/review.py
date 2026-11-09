"""Export review sheets; import only human-marked ok rows without modifying labels."""

from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path

from eval.common import load_items, load_sections, save_items, set_hash
from eval.schema import EvalItem, Section
from support_agent.config import REPO_ROOT, get_settings
from support_agent.data.doc_models import digest, json_text

log = logging.getLogger(__name__)
FIELDS = [
    "id",
    "group",
    "split",
    "question",
    "gold_section_text",
    "answer_points",
    "row_hash",
    "ok",
]


def review_row(item: EvalItem, sections: dict[str, Section], corpus_hash: str) -> dict[str, str]:
    row = {
        "id": item.id,
        "group": item.group,
        "split": item.split,
        "question": item.question,
        "gold_section_text": "\n\n".join(
            f"[{sid}]\n{sections[sid].text}" for sid in item.gold_sections
        ),
        "answer_points": json.dumps(item.answer_points, ensure_ascii=False),
    }
    return {**row, "row_hash": digest(corpus_hash + json.dumps(row, sort_keys=True)), "ok": ""}


def export_review(items: list[EvalItem], sections: dict[str, Section], path: Path) -> None:
    corpus_hash = digest(json_text([section.model_dump() for section in sections.values()]))
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as handle:
            if any(row.get("ok", "").strip() for row in csv.DictReader(handle)):
                raise ValueError("Review CSV contains decisions; use a different export path")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(review_row(item, sections, corpus_hash) for item in items)


def import_review(
    items: list[EvalItem], sections: dict[str, Section], path: Path
) -> list[EvalItem]:
    corpus_hash = digest(json_text([section.model_dump() for section in sections.values()]))
    by_id = {item.id: item for item in items}
    approvals: set[str] = set()
    seen: set[str] = set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            identity = row.get("id", "")
            if identity not in by_id or identity in seen:
                raise ValueError(f"Unknown or duplicate review id: {identity}")
            seen.add(identity)
            expected = review_row(by_id[identity], sections, corpus_hash)
            if any(row.get(key) != value for key, value in expected.items() if key != "ok"):
                raise ValueError(f"Edited or stale review content: {identity}")
            if row.get("ok", "").strip().casefold() == "ok":
                approvals.add(identity)
    return [
        item.model_copy(update={"reviewed": True}) if item.id in approvals else item
        for item in items
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--import-csv", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = get_settings()
    folder = REPO_ROOT / settings.evaluation.sets_dir
    path = folder / "eval_v1.jsonl"
    try:
        items = load_items(path)
        sections = load_sections(settings)
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        if set_hash(items) != manifest["set_hash"]:
            raise ValueError("Frozen eval questions/labels changed")
        if args.import_csv:
            updated = import_review(items, sections, args.import_csv)
            save_items(path, updated)
            log.info("reviewed: %d/%d", sum(item.reviewed for item in updated), len(updated))
        else:
            output = args.output or folder / "review.csv"
            export_review(items, sections, output)
            log.info("exported %d rows with blank ok cells to %s", len(items), output)
    except (OSError, ValueError, KeyError) as exc:
        log.error("review failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
