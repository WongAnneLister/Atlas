"""Download pinned raw datasets from the Hugging Face Hub into `data/raw/<name>/`.

One of only two modules that touch the network (the other is `licenses.py`).
Run with `make data-download`.
"""

from __future__ import annotations

import argparse
import logging
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from support_agent.config import REPO_ROOT, DataSource, get_settings
from support_agent.data.manifest import (
    Manifest,
    SourceRecord,
    describe_file,
    is_current,
    load_manifest,
    write_manifest,
)

log = logging.getLogger(__name__)

# (repo_id, filename, revision, dest_dir) -> path of the downloaded file
Fetcher = Callable[[str, str, str, Path], Path]


class DownloadError(RuntimeError):
    """Raised with a readable message when a dataset cannot be fetched."""


def hf_fetch(repo_id: str, filename: str, revision: str, dest_dir: Path) -> Path:
    """Fetch one file from a dataset repo at an exact revision."""
    from huggingface_hub import hf_hub_download
    from huggingface_hub.errors import (
        EntryNotFoundError,
        LocalEntryNotFoundError,
        RepositoryNotFoundError,
        RevisionNotFoundError,
    )

    try:
        path = hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            repo_type="dataset",
            revision=revision,
            local_dir=dest_dir,
        )
    except RepositoryNotFoundError as exc:
        raise DownloadError(
            f"{repo_id}: repository not found (removed, renamed or private)."
        ) from exc
    except RevisionNotFoundError as exc:
        raise DownloadError(f"{repo_id}: revision {revision} not found.") from exc
    except EntryNotFoundError as exc:
        raise DownloadError(f"{repo_id}: file {filename} not found at {revision}.") from exc
    except LocalEntryNotFoundError as exc:
        raise DownloadError(
            f"{repo_id}: cannot reach the Hugging Face Hub. Check your network or HF_ENDPOINT."
        ) from exc
    except OSError as exc:  # connection errors from the HTTP stack
        msg = f"{repo_id}: network error while downloading {filename}: {exc}"
        raise DownloadError(msg) from exc
    return Path(path)


def download_source(
    source: DataSource,
    raw_dir: Path,
    manifest: Manifest,
    fetch: Fetcher = hf_fetch,
    today: str | None = None,
) -> bool:
    """Download one source unless it is already present at the same revision.

    Returns True if files were downloaded, False if skipped. Updates `manifest` in place.
    """
    source_dir = raw_dir / source.name
    existing = manifest.sources.get(source.name)
    if is_current(existing, source.revision, source_dir):
        log.info("skip %s: already at %s", source.name, source.revision[:12])
        return False

    if source_dir.exists():
        shutil.rmtree(source_dir)  # stale revision or partial download
    source_dir.mkdir(parents=True)
    log.info("download %s @ %s", source.repo_id, source.revision[:12])
    paths = [fetch(source.repo_id, f, source.revision, source_dir) for f in source.files]
    # hf_hub_download keeps a `.cache/` folder inside local_dir; it is not data.
    shutil.rmtree(source_dir / ".cache", ignore_errors=True)

    manifest.sources[source.name] = SourceRecord(
        name=source.name,
        repo_id=source.repo_id,
        revision=source.revision,
        downloaded_at=today or datetime.now(UTC).date().isoformat(),
        files=[describe_file(p, source_dir) for p in sorted(paths)],
    )
    return True


def download_all(
    sources: list[DataSource],
    raw_dir: Path,
    fetch: Fetcher = hf_fetch,
    prune: bool = True,
) -> Manifest:
    """Download every source, then write `MANIFEST.json`.

    With `prune`, manifest entries for sources no longer in config are dropped.
    """
    manifest = load_manifest(raw_dir)
    if prune:
        wanted = {s.name for s in sources}
        for name in list(manifest.sources):
            if name not in wanted:
                del manifest.sources[name]
    for source in sources:
        download_source(source, raw_dir, manifest, fetch)
        write_manifest(raw_dir, manifest)  # after each source, so progress survives a failure
    write_manifest(raw_dir, manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="*", help="source names to download (default: all)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    settings = get_settings()
    sources = settings.data.sources
    if args.only:
        sources = [s for s in sources if s.name in set(args.only)]
    raw_dir = REPO_ROOT / settings.data.raw_dir
    try:
        manifest = download_all(sources, raw_dir, prune=not args.only)
    except DownloadError as exc:
        log.error("%s", exc)
        return 1
    for rec in manifest.sources.values():
        rows = ", ".join(f"{f.path}={f.rows}" for f in rec.files)
        log.info("%s @ %s: %s", rec.name, rec.revision[:12], rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
