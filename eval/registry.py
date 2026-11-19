"""Inventory and verify versioned local evaluation datasets."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, TypeAdapter, model_validator

from support_agent.config import REPO_ROOT
from support_agent.data.doc_models import write_text

REGISTRY_PATH = REPO_ROOT / "eval/registry.yaml"


class DatasetEntry(BaseModel):
    name: str = Field(min_length=1)
    version: str = Field(pattern=r"^v[1-9][0-9]*$")
    path: Path
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    items: int = Field(gt=0)
    splits: dict[str, int]
    reviewed: int = Field(ge=0)
    license_scope: Literal["local_only"] = "local_only"
    changelog: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def check_fields(self) -> DatasetEntry:
        if self.path.is_absolute() or ".." in self.path.parts:
            raise ValueError("Dataset path must be relative to the repository")
        if (
            any(size <= 0 for size in self.splits.values())
            or sum(self.splits.values()) != self.items
            or self.reviewed > self.items
        ):
            raise ValueError("Dataset counts do not reconcile")
        if any(not line.strip() for line in self.changelog):
            raise ValueError("Changelog lines must be nonempty")
        return self


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, DatasetEntry]:
    entries = TypeAdapter(list[DatasetEntry]).validate_python(
        yaml.safe_load(path.read_text(encoding="utf-8"))["datasets"]
    )
    registry = {entry.name: entry for entry in entries}
    if len(registry) != len(entries) or len({entry.path for entry in entries}) != len(entries):
        raise ValueError("Registry contains duplicate dataset names or paths")
    return registry


def dataset_for_path(path: Path) -> DatasetEntry | None:
    return next(
        (entry for entry in load_registry().values() if REPO_ROOT / entry.path == path.resolve()),
        None,
    )


def write_registry(entries: dict[str, DatasetEntry], path: Path = REGISTRY_PATH) -> None:
    payload = {"datasets": [entry.model_dump(mode="json") for entry in entries.values()]}
    write_text(path, yaml.safe_dump(payload, sort_keys=False))


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect_dataset(
    path: Path, *, name: str, version: str, changelog: list[str], root: Path = REPO_ROOT
) -> DatasetEntry:
    content = path.read_bytes()
    splits: Counter[str] = Counter()
    ids: set[str] = set()
    reviewed = 0
    for number, line in enumerate(content.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError(f"{path.name}:{number}: invalid JSON") from None
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("id"), str)
            or not row["id"]
            or not isinstance(row.get("split"), str)
            or not row["split"]
            or not isinstance(row.get("reviewed", False), bool)
        ):
            raise ValueError(f"{path.name}:{number}: expected id, split and optional review flag")
        if row["id"] in ids:
            raise ValueError(f"{path.name}:{number}: duplicate item ID")
        ids.add(row["id"])
        splits[row["split"]] += 1
        reviewed += row.get("reviewed", False)
    return DatasetEntry(
        name=name,
        version=version,
        path=path.relative_to(root),
        sha256=hashlib.sha256(content).hexdigest(),
        items=len(ids),
        splits=dict(sorted(splits.items())),
        reviewed=reviewed,
        changelog=changelog,
    )


def validate(
    entries: dict[str, DatasetEntry], *, require_present: bool = False, root: Path = REPO_ROOT
) -> tuple[list[str], int]:
    messages = []
    status = 0
    for entry in entries.values():
        path = root / entry.path
        if not path.is_file():
            result = "FAIL (missing)" if require_present else "SKIP (local only)"
            messages.append(f"{entry.name}: {result} {entry.path}")
            status |= int(require_present)
            continue
        if file_hash(path) != entry.sha256:
            messages.append(
                f"{entry.name}: FAIL hash mismatch; bump the version and add a changelog line"
            )
            status = 1
            continue
        actual = inspect_dataset(
            path, name=entry.name, version=entry.version, changelog=entry.changelog, root=root
        )
        if actual != entry:
            messages.append(f"{entry.name}: FAIL registry counts differ from the dataset")
            status = 1
        else:
            messages.append(f"{entry.name}: OK {entry.version} ({entry.items} items)")
    return messages, status


def bump(entry: DatasetEntry, version: str, note: str, *, root: Path = REPO_ROOT) -> DatasetEntry:
    if not version.startswith("v") or not version[1:].isdecimal():
        raise ValueError("Use a version of the form vN")
    if int(version[1:]) <= int(entry.version[1:]):
        raise ValueError(f"New version must be higher than {entry.version}")
    return inspect_dataset(
        root / entry.path,
        name=entry.name,
        version=version,
        changelog=[*entry.changelog, note.strip()],
        root=root,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validation = commands.add_parser("validate")
    validation.add_argument("--require-present", action="store_true")
    promotion = commands.add_parser("bump")
    promotion.add_argument("name")
    promotion.add_argument("--version", required=True)
    promotion.add_argument("--note", required=True)
    args = parser.parse_args(argv)
    entries = load_registry()
    if args.command == "validate":
        messages, status = validate(entries, require_present=args.require_present)
        sys.stdout.write("\n".join(messages) + "\n")
        return status
    if args.name not in entries:
        parser.error(f"Unknown dataset: {args.name}")
    try:
        entries[args.name] = bump(entries[args.name], args.version, args.note)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    write_registry(entries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
