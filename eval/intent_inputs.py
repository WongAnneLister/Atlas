"""Fail before inference when frozen benchmark sources or construction code changed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eval.intent_records import IntentItem
from support_agent.config import REPO_ROOT, Settings
from support_agent.data.doc_models import digest, json_text


def artifact_hashes(settings: Settings, root: Path = REPO_ROOT) -> dict[str, str]:
    source = next(s for s in settings.data.sources if s.name == "bitext")
    files = {
        "raw_hash": root / settings.data.raw_dir / "bitext" / source.files[0],
        "retrieval_eval_hash": root / settings.evaluation.sets_dir / "eval_v1.jsonl",
        "draft_hash": root / settings.intent_eval.extra_drafts,
        "prompt_hash": root / "src/support_agent/graph/prompts/classify.md",
    }
    hashes = {name: digest(path.read_text()) for name, path in files.items()}
    builder_files = (
        "eval/intent_data.py",
        "eval/intent_inputs.py",
        "eval/intent_records.py",
        "eval/common.py",
        "eval/schema.py",
        "src/support_agent/data/doc_models.py",
        "src/support_agent/data/intent_map.py",
        "src/support_agent/graph/intents.py",
    )
    hashes["builder_hash"] = digest(
        json_text([[name, digest((root / name).read_text())] for name in builder_files])
    )
    return hashes


def load_benchmark(
    settings: Settings, root: Path = REPO_ROOT
) -> tuple[list[IntentItem], dict[str, Any]]:
    folder = root / settings.evaluation.sets_dir
    manifest = json.loads((folder / "intent_manifest.json").read_text())
    data = (folder / "intent_holdout.jsonl").read_text()
    hashes = {**artifact_hashes(settings, root), "dataset_hash": digest(data)}
    for name, actual in hashes.items():
        if manifest.get(name) != actual:
            raise ValueError(f"Frozen intent {name} changed; rebuild explicitly")
    if manifest["sampling"] != settings.intent_eval.model_dump(mode="json"):
        raise ValueError("Intent sampling settings changed; rebuild explicitly")
    items = [IntentItem.model_validate_json(line) for line in data.splitlines()]
    if not items or len({i.id for i in items}) != len(items):
        raise ValueError("Intent holdout must contain unique nonempty items")
    return items, manifest
