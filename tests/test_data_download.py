"""Offline tests for the downloader and manifest (fake fetcher, temp dir)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from support_agent.config import DataSource
from support_agent.data.download import DownloadError, download_all, download_source
from support_agent.data.manifest import MANIFEST_NAME, Manifest, load_manifest, sha256_file

CSV = "question,answer\nHow do I return?,Use My Orders.\nWhere is my order?,Track it.\n"


class FakeFetcher:
    """Writes canned bytes instead of calling the Hub, and counts calls."""

    def __init__(self, content: dict[str, str]) -> None:
        self.content = content
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, repo_id: str, filename: str, revision: str, dest_dir: Path) -> Path:
        self.calls.append((repo_id, filename, revision))
        path = dest_dir / filename
        path.write_text(self.content[filename], encoding="utf-8")
        return path


def _source(revision: str = "rev1") -> DataSource:
    return DataSource(
        name="faqs", repo_id="org/faqs", revision=revision, role="test", files=["faqs.csv"]
    )


def test_manifest_records_rows_columns_and_hash(tmp_path: Path) -> None:
    fetch = FakeFetcher({"faqs.csv": CSV})
    manifest = download_all([_source()], tmp_path, fetch, prune=True)

    rec = manifest.sources["faqs"]
    assert rec.revision == "rev1"
    (f,) = rec.files
    assert (f.path, f.kind, f.rows, f.columns) == ("faqs.csv", "csv", 2, ["question", "answer"])
    assert f.sha256 == sha256_file(tmp_path / "faqs" / "faqs.csv")

    on_disk = json.loads((tmp_path / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert on_disk["sources"]["faqs"]["files"][0]["rows"] == 2
    assert load_manifest(tmp_path) == manifest


def test_manifest_is_byte_stable(tmp_path: Path) -> None:
    download_all([_source()], tmp_path, FakeFetcher({"faqs.csv": CSV}))
    first = (tmp_path / MANIFEST_NAME).read_bytes()
    download_all([_source()], tmp_path, FakeFetcher({"faqs.csv": CSV}))
    assert (tmp_path / MANIFEST_NAME).read_bytes() == first


def test_skip_when_same_revision(tmp_path: Path) -> None:
    fetch = FakeFetcher({"faqs.csv": CSV})
    download_all([_source()], tmp_path, fetch)
    download_all([_source()], tmp_path, fetch)
    assert len(fetch.calls) == 1


def test_redownload_when_revision_changes(tmp_path: Path) -> None:
    fetch = FakeFetcher({"faqs.csv": CSV})
    download_all([_source("rev1")], tmp_path, fetch)
    download_all([_source("rev2")], tmp_path, fetch)
    assert [c[2] for c in fetch.calls] == ["rev1", "rev2"]
    assert load_manifest(tmp_path).sources["faqs"].revision == "rev2"


def test_redownload_when_file_corrupted(tmp_path: Path) -> None:
    fetch = FakeFetcher({"faqs.csv": CSV})
    download_all([_source()], tmp_path, fetch)
    (tmp_path / "faqs" / "faqs.csv").write_text("tampered", encoding="utf-8")
    download_all([_source()], tmp_path, fetch)
    assert len(fetch.calls) == 2


def test_jsonl_named_json_is_counted(tmp_path: Path) -> None:
    src = DataSource(name="m", repo_id="o/m", revision="r", role="t", files=["d.json"])
    lines = '{"question": "a", "answer": "b"}\n{"question": "c", "answer": "d"}\n'
    manifest = Manifest()
    download_source(src, tmp_path, manifest, FakeFetcher({"d.json": lines}), today="2026-01-01")
    (f,) = manifest.sources["m"].files
    assert (f.rows, f.columns) == (2, ["answer", "question"])
    assert manifest.sources["m"].downloaded_at == "2026-01-01"


def test_prune_drops_removed_sources(tmp_path: Path) -> None:
    download_all([_source()], tmp_path, FakeFetcher({"faqs.csv": CSV}))
    assert download_all([], tmp_path, FakeFetcher({}), prune=True).sources == {}


def test_download_error_propagates(tmp_path: Path) -> None:
    def offline(repo_id: str, filename: str, revision: str, dest_dir: Path) -> Path:
        raise DownloadError(f"{repo_id}: cannot reach the Hugging Face Hub.")

    with pytest.raises(DownloadError, match="cannot reach"):
        download_all([_source()], tmp_path, offline)
    assert "faqs" not in load_manifest(tmp_path).sources
