"""Export a blind review CSV and import labels supplied by a person."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from eval.build_claims import CLAIMS_PATH, NAME, publish_claims, read_claims
from eval.registry import file_hash, load_registry
from eval.schema import ClaimItem
from support_agent.config import REPO_ROOT

LABELS_PATH = REPO_ROOT / "eval/sets/claims_v1_labels.csv"
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
    parser.add_argument("--version", help="New registry version for an import")
    args = parser.parse_args(argv)
    try:
        entry = load_registry()[NAME]
        if file_hash(CLAIMS_PATH) != entry.sha256:
            raise ValueError("Local claim set differs from the registry")
        path = args.csv.resolve()
        path.relative_to(REPO_ROOT)
        items = read_claims()
        if args.import_labels:
            updated = import_labels(items, path)
            publish_claims(updated, version=args.version, note="Import human claim labels.")
        else:
            export_labels(items, path)
    except (KeyError, ValueError, OSError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
