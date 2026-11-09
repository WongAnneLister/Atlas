"""Manifest of downloaded raw datasets: file hashes, row counts and columns.

Pure local code: reads files under `data/raw/`, never touches the network.
"""

from __future__ import annotations

import csv
import hashlib
import json
import zipfile
from pathlib import Path

from pydantic import BaseModel, Field

MANIFEST_NAME = "MANIFEST.json"
_HASH_CHUNK = 1 << 20


class FileRecord(BaseModel):
    path: str  # relative to the source directory, POSIX style
    sha256: str
    size_bytes: int
    kind: str  # csv | json | jsonl | parquet | zip | other
    rows: int | None = None  # tabular rows, or archive entries for zip
    columns: list[str] = Field(default_factory=list)


class SourceRecord(BaseModel):
    name: str
    repo_id: str
    revision: str
    downloaded_at: str  # ISO date (UTC)
    files: list[FileRecord]


class Manifest(BaseModel):
    sources: dict[str, SourceRecord] = Field(default_factory=dict)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _csv_stats(path: Path) -> tuple[int, list[str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, [])
        return sum(1 for _ in reader), header


def _json_stats(path: Path) -> tuple[int | None, list[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # Some Hub files named `.json` are really JSON Lines (e.g. MakTek).
        return _jsonl_stats(path)
    if isinstance(data, list):
        cols = sorted({k for row in data if isinstance(row, dict) for k in row})
        return len(data), cols
    if isinstance(data, dict):
        return None, sorted(data)
    return None, []


def _jsonl_stats(path: Path) -> tuple[int, list[str]]:
    rows, cols = 0, set[str]()
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows += 1
                obj = json.loads(line)
                if isinstance(obj, dict):
                    cols.update(obj)
    return rows, sorted(cols)


def _zip_stats(path: Path) -> tuple[int, list[str]]:
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
    return len(names), sorted(names)


def describe_file(path: Path, source_dir: Path) -> FileRecord:
    """Hash a file and, for known formats, count rows and list columns."""
    suffix = path.suffix.lower()
    rows: int | None = None
    columns: list[str] = []
    kind = "other"
    if suffix == ".csv":
        kind, (rows, columns) = "csv", _csv_stats(path)
    elif suffix == ".jsonl":
        kind, (rows, columns) = "jsonl", _jsonl_stats(path)
    elif suffix == ".json":
        kind, (rows, columns) = "json", _json_stats(path)
    elif suffix == ".zip":
        kind, (rows, columns) = "zip", _zip_stats(path)
    elif suffix == ".parquet":
        kind = "parquet"
        import pyarrow.parquet as pq  # local import: optional heavy dependency

        meta = pq.ParquetFile(path).metadata
        rows, columns = meta.num_rows, list(meta.schema.names)
    return FileRecord(
        path=path.relative_to(source_dir).as_posix(),
        sha256=sha256_file(path),
        size_bytes=path.stat().st_size,
        kind=kind,
        rows=rows,
        columns=columns,
    )


def load_manifest(raw_dir: Path) -> Manifest:
    path = raw_dir / MANIFEST_NAME
    if not path.exists():
        return Manifest()
    return Manifest.model_validate_json(path.read_text(encoding="utf-8"))


def write_manifest(raw_dir: Path, manifest: Manifest) -> Path:
    """Write the manifest with sorted keys so reruns give identical bytes."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / MANIFEST_NAME
    data = manifest.model_dump(mode="json")
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def is_current(record: SourceRecord | None, revision: str, source_dir: Path) -> bool:
    """True if the manifest entry matches the revision and every file is intact on disk."""
    if record is None or record.revision != revision or not record.files:
        return False
    for f in record.files:
        p = source_dir / f.path
        if not p.is_file() or p.stat().st_size != f.size_bytes or sha256_file(p) != f.sha256:
            return False
    return True
