"""Load local chunk text only with matching build provenance."""

import re
from pathlib import Path

from pydantic import BaseModel

from support_agent.config import REPO_ROOT, Settings
from support_agent.data.doc_models import digest
from support_agent.retrieval.chunking import Chunk


class Snapshot(BaseModel):
    build_id: str | None = None
    chunk_hash: str


def build_snapshot_path(settings: Settings, build_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]+", build_id):
        raise ValueError("Invalid snapshot build id")
    return REPO_ROOT / settings.data.processed_dir / settings.index.builds_directory / build_id


def _verified_text(path: Path, metadata: Snapshot, expected: str | None) -> str:
    if metadata.build_id != expected:
        raise ValueError("Local chunk snapshot does not match the expected build id")
    raw = path.read_bytes().decode("utf-8")
    if digest(raw) != metadata.chunk_hash:
        raise ValueError("Local chunk snapshot checksum differs from its recorded build")
    return raw


def _load(path: Path, metadata: Snapshot, expected: str | None) -> list[Chunk]:
    return [
        Chunk.model_validate_json(line)
        for line in _verified_text(path, metadata, expected).splitlines()
        if line
    ]


def build_chunk_hash(settings: Settings, build_id: str) -> str:
    path = build_snapshot_path(settings, build_id)
    meta = Snapshot.model_validate_json((path / "snapshot.json").read_bytes())
    _verified_text(path / "chunks.jsonl", meta, build_id)
    return meta.chunk_hash


def load_build_chunks(settings: Settings, build_id: str) -> list[Chunk]:
    path = build_snapshot_path(settings, build_id)
    meta = Snapshot.model_validate_json((path / "snapshot.json").read_bytes())
    return _load(path / "chunks.jsonl", meta, build_id)


def load_latest_chunks(settings: Settings, *, expected_build_id: str | None) -> list[Chunk]:
    path = REPO_ROOT / settings.data.processed_dir
    meta = Snapshot.model_validate_json((path / "ingest_run.json").read_bytes())
    return _load(path / "chunks.jsonl", meta, expected_build_id)


def load_build_input(settings: Settings) -> list[Chunk]:
    """Explicit experiment builds use the latest file as source material, not hydration."""
    path = REPO_ROOT / settings.data.processed_dir
    meta = Snapshot.model_validate_json((path / "ingest_run.json").read_bytes())
    return _load(path / "chunks.jsonl", meta, meta.build_id)
