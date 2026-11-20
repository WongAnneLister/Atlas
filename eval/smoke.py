"""Materialize the frozen test smoke set without committing question text."""

from __future__ import annotations

import argparse
import random
import sys
from collections import Counter
from collections.abc import Sequence
from hashlib import sha256
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from eval.common import load_items
from eval.redteam_models import CATEGORIES, RedTeamItem
from eval.registry import DatasetEntry, file_hash, inspect_dataset, load_registry, write_registry
from eval.schema import GROUPS, EvalItem
from support_agent.config import REPO_ROOT, get_settings
from support_agent.data.doc_models import write_text

SMOKE_PATH = REPO_ROOT / "eval/smoke.yaml"
OUTPUT_PATH = REPO_ROOT / "eval/sets/smoke.jsonl"
STRATA = {group: 30 if group == "no_answer" else 10 for group in GROUPS}
REDTEAM_SMOKE_SIZE = 30
RULE = "All test no-answer items and a seeded sample of ten from each answerable test group."


class SmokeSpec(BaseModel):
    seed: int
    rule: str
    source: Literal["eval_v1"] = "eval_v1"
    source_version: str
    source_sha256: str
    item_ids: list[str] = Field(min_length=1)
    redteam: list[str] = Field(default_factory=list, max_length=REDTEAM_SMOKE_SIZE)

    @field_validator("redteam")
    @classmethod
    def _redteam_coverage(cls, ids: list[str]) -> list[str]:
        if ids and (
            len(set(ids)) != REDTEAM_SMOKE_SIZE
            or {item_id.partition("-")[0] for item_id in ids} != set(CATEGORIES)
        ):
            raise ValueError("Red-team smoke requires 30 unique IDs covering every category")
        return ids


def load_smoke_spec(path: Path = SMOKE_PATH) -> SmokeSpec:
    return SmokeSpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def select_redteam_smoke(items: Sequence[RedTeamItem], seed: int) -> list[str]:
    """Sample each category separately from the test split."""
    rng = random.Random(seed)
    size, remainder = divmod(REDTEAM_SMOKE_SIZE, len(CATEGORIES))
    extra = set(rng.sample(CATEGORIES, remainder))
    selected = []
    for category in CATEGORIES:
        members = sorted(
            item.id for item in items if item.category == category and item.split == "test"
        )
        selected.extend(rng.sample(members, size + (category in extra)))
    return selected


def _validate_selection(rows: list[EvalItem], selected: list[EvalItem]) -> None:
    expected_no_answer = {row.id for row in rows if row.split == "test" and not row.answerable}
    actual_no_answer = {row.id for row in selected if not row.answerable}
    if (
        Counter(row.group for row in selected) != STRATA
        or actual_no_answer != expected_no_answer
        or any(row.split != "test" for row in selected)
        or len({row.id for row in selected}) != len(selected)
    ):
        raise ValueError(
            "Smoke selection must contain all 30 test no-answer rows and 10 per answerable group"
        )


def select_smoke(rows: list[EvalItem], seed: int) -> list[EvalItem]:
    rng = random.Random(seed)
    selected = []
    for group in GROUPS:
        members = sorted(
            (row for row in rows if row.split == "test" and row.group == group),
            key=lambda row: row.id,
        )
        selected.extend(members if group == "no_answer" else rng.sample(members, STRATA[group]))
    _validate_selection(rows, selected)
    return selected


def _from_spec(spec: SmokeSpec, source: DatasetEntry, rows: list[EvalItem]) -> list[EvalItem]:
    if (spec.source_version, spec.source_sha256) != (source.version, source.sha256):
        raise ValueError(
            "Frozen smoke selection does not match the registered source version and hash"
        )
    by_id = {row.id: row for row in rows}
    if any(item_id not in by_id for item_id in spec.item_ids):
        raise ValueError("Frozen smoke selection contains an unknown item ID")
    selected = [by_id[item_id] for item_id in spec.item_ids]
    _validate_selection(rows, selected)
    return selected


def build_smoke() -> DatasetEntry:
    registry = load_registry()
    source = registry["eval_v1"]
    source_path = REPO_ROOT / source.path
    if not source_path.is_file():
        raise FileNotFoundError(f"Missing local smoke source {source.path}")
    if file_hash(source_path) != source.sha256:
        raise ValueError("Smoke source hash differs from its registered version")
    rows = load_items(source_path)

    existing = registry.get("smoke")
    if SMOKE_PATH.is_file():
        spec = load_smoke_spec(SMOKE_PATH)
        selected = _from_spec(spec, source, rows)
    elif existing is None:
        seed = get_settings().evaluation.seed
        selected = select_smoke(rows, seed)
        spec = SmokeSpec(
            seed=seed,
            rule=RULE,
            source_version=source.version,
            source_sha256=source.sha256,
            item_ids=[row.id for row in selected],
        )
    else:
        raise FileNotFoundError("Missing frozen smoke selection eval/smoke.yaml")

    content = "".join(f"{row.model_dump_json()}\n" for row in selected)
    output = REPO_ROOT / existing.path if existing else OUTPUT_PATH
    if existing:
        if sha256(content.encode("utf-8")).hexdigest() != existing.sha256:
            raise ValueError("Materialized smoke hash does not match the registry")
        write_text(output, content)
        return existing

    write_text(output, content)
    entry = inspect_dataset(
        output, name="smoke", version="v1", changelog=["Freeze stratified v1 test smoke selection"]
    )
    write_text(SMOKE_PATH, yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False))
    registry["smoke"] = entry
    write_registry(registry)
    return entry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        entry = build_smoke()
    except (ValueError, OSError) as error:
        parser.error(str(error))
    sys.stdout.write(f"Built {entry.path} ({entry.items} items, {entry.version})\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
