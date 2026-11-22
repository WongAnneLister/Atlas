"""Local cache of cross-encoder logits for release-evidence runs.

A release check reranks about 50 candidates for each of 220 frozen questions on both the
live and the candidate collection. After a one-section change almost every (query, passage)
pair is the same as in the live run, so its logit can be read back instead of recomputed.

The key holds everything the logit depends on: reranker model and revision, device, fp16
flag, max tokens, batch size (padding is per batch), the installed versions of the
configured packages, the exact query text and the passage text hash. Anything else is a
miss. The serving path never uses this module.
"""

from __future__ import annotations

import hashlib
import math
import sqlite3
from collections.abc import Callable, Mapping
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from support_agent.config import REPO_ROOT, Settings
from support_agent.data.doc_models import digest, json_text
from support_agent.retrieval.rerank import rank_by_logits
from support_agent.retrieval.types import RetrievedChunk

_SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    profile_hash TEXT PRIMARY KEY,
    profile_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scores (
    profile_hash TEXT NOT NULL,
    query_sha256 TEXT NOT NULL,
    passage_sha256 TEXT NOT NULL,
    logit REAL NOT NULL,
    PRIMARY KEY (profile_hash, query_sha256, passage_sha256)
) WITHOUT ROWID;
"""


class LogitScorer(Protocol):
    def logits(self, query: str, texts: list[str]) -> list[float]: ...


class ScoreProfile(BaseModel):
    """Every model-side input of a logit; part of the cache key."""

    model_config = ConfigDict(frozen=True)

    model: str
    revision: str
    device: str
    use_fp16: bool
    max_tokens: int
    batch_size: int
    packages: dict[str, str | None]

    @property
    def key(self) -> str:
        return digest(json_text(self.model_dump(mode="json")))


def installed_version(package: str) -> str | None:
    try:
        return version(package)
    except PackageNotFoundError:
        return None


def score_profile(
    settings: Settings, package_version: Callable[[str], str | None] = installed_version
) -> ScoreProfile:
    retrieval = settings.retrieval
    return ScoreProfile(
        model=retrieval.reranker_model,
        revision=retrieval.reranker_revision,
        device=retrieval.reranker_device,
        use_fp16=retrieval.reranker_use_fp16,
        max_tokens=retrieval.reranker_max_tokens,
        batch_size=retrieval.reranker_batch_size,
        packages={
            name: package_version(name) for name in settings.index.release.rerank_cache.key_packages
        },
    )


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cache_path(settings: Settings) -> Path | None:
    cache = settings.index.release.rerank_cache
    if not cache.enabled:
        return None
    path = Path(cache.path)
    return path if path.is_absolute() else REPO_ROOT / path


class ScoreCache:
    """SQLite file of logits; writes are committed per query so a dropped run keeps its work."""

    def __init__(self, path: Path, profile: ScoreProfile) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.profile = profile
        self._connection = sqlite3.connect(path)
        self._connection.executescript(_SCHEMA)
        with self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO profiles VALUES (?, ?)",
                (profile.key, json_text(profile.model_dump(mode="json"))),
            )

    def get(self, query: str, passages: list[str]) -> dict[str, float]:
        """Cached logits by passage hash for this profile and query."""
        hashes = sorted(set(passages))
        if not hashes:
            return {}
        marks = ",".join("?" * len(hashes))
        rows = self._connection.execute(
            "SELECT passage_sha256, logit FROM scores WHERE profile_hash = ? "
            f"AND query_sha256 = ? AND passage_sha256 IN ({marks})",
            (self.profile.key, text_sha256(query), *hashes),
        )
        return {passage: float(logit) for passage, logit in rows}

    def put(self, query: str, logits: Mapping[str, float]) -> None:
        query_hash = text_sha256(query)
        with self._connection:
            self._connection.executemany(
                "INSERT OR IGNORE INTO scores VALUES (?, ?, ?, ?)",
                [
                    (self.profile.key, query_hash, passage, logit)
                    for passage, logit in logits.items()
                ],
            )

    def close(self) -> None:
        self._connection.close()


class CachedReranker:
    """Rerank with cached logits where the key matches; score only the rest.

    With ``cache=None`` every pair is scored, exactly like ``BgeReranker.rerank``.
    On a cold cache the scorer sees the same pairs in the same order as without a cache.
    """

    def __init__(self, scorer: LogitScorer, cache: ScoreCache | None) -> None:
        self.scorer = scorer
        self.cache = cache
        self.from_cache = 0
        self.scored = 0

    def rerank(self, query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        if not chunks:
            return []
        if self.cache is None:
            self.scored += len(chunks)
            return rank_by_logits(chunks, self.scorer.logits(query, [c.text for c in chunks]))
        hashes = [text_sha256(chunk.text) for chunk in chunks]
        known = self.cache.get(query, hashes)
        missing = [i for i, passage in enumerate(hashes) if passage not in known]
        fresh: dict[int, float] = {}
        if missing:
            values = self.scorer.logits(query, [chunks[i].text for i in missing])
            if len(values) != len(missing) or not all(math.isfinite(v) for v in values):
                raise ValueError("Reranker must return one finite logit per missing pair")
            fresh = dict(zip(missing, values, strict=True))
            self.cache.put(query, {hashes[i]: value for i, value in fresh.items()})
        self.from_cache += len(chunks) - len(missing)
        self.scored += len(missing)
        logits = [fresh[i] if i in fresh else known[passage] for i, passage in enumerate(hashes)]
        return rank_by_logits(chunks, logits)

    def summary(self) -> dict[str, Any]:
        return {
            "cache": _display(self.cache.path) if self.cache else None,
            "profile": self.cache.profile.key if self.cache else None,
            "from_cache": self.from_cache,
            "scored": self.scored,
        }


def _display(path: Path) -> str:
    resolved = path.resolve()
    root = REPO_ROOT.resolve()
    return str(resolved.relative_to(root)) if resolved.is_relative_to(root) else resolved.name
