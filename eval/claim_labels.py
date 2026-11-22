"""Export blind label CSVs and import labels from the author or a model draft.

Labels are the author's. A model may draft them (`--import --drafted-by-model`); the author
then reviews a seeded blind sample that includes every drafted `unsupported` claim
(`--review-sample`, `--import-review`). Reviewed rows become human labels and keep the draft
for agreement. Drafts that were not reviewed stay marked `model_draft`.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from random import Random
from typing import Any

from eval.build_claims import CLAIMS_PATH, NAME, publish_claims, read_claims
from eval.registry import file_hash, load_registry
from eval.schema import ClaimItem
from support_agent.config import REPO_ROOT

LABELS_PATH = REPO_ROOT / "eval/sets/claims_v1_labels.csv"
REVIEW_PATH = REPO_ROOT / "eval/sets/claims_v1_review.csv"
FIELDS = ("id", "split", "question", "claim", "sources", "label", "note")


def _sources(item: ClaimItem) -> str:
    return json.dumps([source.model_dump() for source in item.sources], ensure_ascii=False)


def export_labels(items: list[ClaimItem], path: Path) -> None:
    with path.open("x", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        for item in items:
            if item.group == "real":
                writer.writerow(
                    {
                        "id": item.id,
                        "split": item.split,
                        "question": item.question,
                        "claim": item.claim,
                        "sources": _sources(item),
                        "label": "",
                        "note": "",
                    }
                )


def _read_labelled_rows(
    expected: dict[str, ClaimItem], path: Path
) -> dict[str, tuple[ClaimItem, str, str]]:
    rows: dict[str, tuple[ClaimItem, str, str]] = {}
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError("Unexpected claim label CSV columns")
        for row in reader:
            key = row["id"]
            if key not in expected or key in rows:
                raise ValueError(f"Unknown or duplicate claim id: {key}")
            item = expected[key]
            if (row["question"], row["claim"], row["split"], row["sources"]) != (
                item.question,
                item.claim,
                item.split,
                _sources(item),
            ):
                raise ValueError(f"Claim question, text, split or sources changed for {key}")
            if row["label"] not in {"supported", "unsupported"}:
                raise ValueError(f"Missing or invalid label for {key}")
            if row["note"] is None or None in row:
                raise ValueError(f"Invalid CSV row for {key}")
            rows[key] = (item, row["label"], row["note"])
    return rows


def import_drafts(items: list[ClaimItem], path: Path) -> list[ClaimItem]:
    """Import a complete set of model-drafted labels, marked as unreviewed drafts."""
    expected = {item.id: item for item in items if item.group == "real"}
    rows = _read_labelled_rows(expected, path)
    if rows.keys() != expected.keys():
        raise ValueError("CSV is missing real claim IDs")
    drafted = {
        key: ClaimItem.model_validate(
            {
                **item.model_dump(),
                "label": label,
                "label_source": "model_draft",
                "reviewed": False,
                "note": "",
                "draft_label": label,
                "draft_note": note,
            }
        )
        for key, (item, label, note) in rows.items()
    }
    return [drafted.get(item.id, item) for item in items]


def review_sample(items: list[ClaimItem], size: int, seed: int) -> list[ClaimItem]:
    """Every drafted unsupported claim plus a seeded sample of drafted supported claims."""
    drafts = sorted(
        (item for item in items if item.label_source == "model_draft"), key=lambda item: item.id
    )
    flagged = [item for item in drafts if item.label == "unsupported"]
    rest = [item for item in drafts if item.label != "unsupported"]
    rng = Random(seed)
    chosen = flagged + rng.sample(rest, min(size, len(rest)))
    rng.shuffle(chosen)
    return chosen


def export_review(items: list[ClaimItem], path: Path, *, size: int, seed: int) -> None:
    """A blind sheet: the author sees the claim and its sources, never the draft."""
    with path.open("x", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        for item in review_sample(items, size, seed):
            writer.writerow(
                {
                    "id": item.id,
                    "split": item.split,
                    "question": item.question,
                    "claim": item.claim,
                    "sources": _sources(item),
                    "label": "",
                    "note": "",
                }
            )


def import_review(items: list[ClaimItem], path: Path) -> tuple[list[ClaimItem], dict[str, Any]]:
    """Replace reviewed drafts with the author's labels and count agreement."""
    expected = {item.id: item for item in items if item.label_source == "model_draft"}
    rows = _read_labelled_rows(expected, path)
    reviewed = {
        key: ClaimItem.model_validate(
            {
                **item.model_dump(),
                "label": label,
                "label_source": "human",
                "reviewed": True,
                "note": note,
            }
        )
        for key, (item, label, note) in rows.items()
    }
    agreement = {
        "reviewed": len(reviewed),
        "agree": sum(item.label == item.draft_label for item in reviewed.values()),
        "draft_unsupported_reviewed": sum(
            item.draft_label == "unsupported" for item in reviewed.values()
        ),
        "changed": sorted(key for key, item in reviewed.items() if item.label != item.draft_label),
    }
    return [reviewed.get(item.id, item) for item in items], agreement


def import_labels(items: list[ClaimItem], path: Path) -> list[ClaimItem]:
    expected = {item.id: item for item in items if item.group == "real"}
    reviewed: dict[str, ClaimItem] = {}
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError("Unexpected claim label CSV columns")
        for row in reader:
            key = row["id"]
            if key not in expected or key in reviewed:
                raise ValueError(f"Unknown or duplicate claim id: {key}")
            item = expected[key]
            if (row["question"], row["claim"], row["split"], row["sources"]) != (
                item.question,
                item.claim,
                item.split,
                _sources(item),
            ):
                raise ValueError(f"Claim question, text, split or sources changed for {key}")
            if row["label"] not in {"supported", "unsupported"}:
                raise ValueError(f"Missing or invalid human label for {key}")
            if row["note"] is None or None in row:
                raise ValueError(f"Invalid CSV row for {key}")
            reviewed[key] = ClaimItem.model_validate(
                {**item.model_dump(), "label": row["label"], "note": row["note"], "reviewed": True}
            )
    if reviewed.keys() != expected.keys():
        raise ValueError("CSV is missing real claim IDs")
    return [reviewed.get(item.id, item) for item in items]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=LABELS_PATH)
    parser.add_argument("--import", action="store_true", dest="import_labels")
    parser.add_argument(
        "--drafted-by-model", action="store_true", help="import the CSV as unreviewed drafts"
    )
    parser.add_argument("--review-sample", type=int, metavar="N", help="export a blind review")
    parser.add_argument("--seed", type=int, default=25)
    parser.add_argument("--import-review", action="store_true")
    parser.add_argument("--version", help="New registry version for an import")
    args = parser.parse_args(argv)
    try:
        entry = load_registry()[NAME]
        if file_hash(CLAIMS_PATH) != entry.sha256:
            raise ValueError("Local claim set differs from the registry")
        path = args.csv.resolve()
        path.relative_to(REPO_ROOT)
        items = read_claims()
        if args.review_sample is not None:
            review = REVIEW_PATH if args.csv == LABELS_PATH else path
            export_review(items, review, size=args.review_sample, seed=args.seed)
        elif args.import_review:
            review = REVIEW_PATH if args.csv == LABELS_PATH else path
            updated, agreement = import_review(items, review)
            publish_claims(
                updated,
                version=args.version,
                note=(
                    f"Author review of model-drafted labels: {agreement['agree']}/"
                    f"{agreement['reviewed']} agree."
                ),
            )
            sys.stdout.write(json.dumps(agreement, indent=2) + "\n")
        elif args.import_labels and args.drafted_by_model:
            updated = import_drafts(items, path)
            publish_claims(updated, version=args.version, note="Import model-drafted claim labels.")
        elif args.import_labels:
            updated = import_labels(items, path)
            publish_claims(updated, version=args.version, note="Import human claim labels.")
        else:
            export_labels(items, path)
    except (KeyError, ValueError, OSError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
