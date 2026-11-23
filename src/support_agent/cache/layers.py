"""Versioned three-layer cache implementations that fail open on Redis errors."""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from typing import Any

from pydantic import BaseModel, Field

from support_agent.cache.keys import (
    answer_bucket_key,
    answer_cache_key,
    build_revision,
    embedding_cache_key,
    index_revision_key,
    normalise_query_text,
    retrieval_cache_key,
    retrieval_config_hash,
)
from support_agent.cache.metrics import CacheLayer, record_cache_event
from support_agent.cache.settings import CacheSettings
from support_agent.config import RetrievalSettings
from support_agent.gate.evidence import GateResult
from support_agent.graph.coverage import CoverageAnswer
from support_agent.graph.state import CitationRecord
from support_agent.grounding.claims import ClaimAssessment
from support_agent.infra.redis import KeyValueStore
from support_agent.retrieval.embed import Embedder
from support_agent.retrieval.filters import RetrievalFilters, filter_scope, supports_filters
from support_agent.retrieval.types import RetrievedChunk, Retriever

logger = logging.getLogger(__name__)


def current_index_revision(store: KeyValueStore | None, settings: CacheSettings) -> str | None:
    if store is None or not settings.enabled:
        return None
    try:
        return store.get(index_revision_key(settings.key_prefix))
    except Exception as error:
        logger.warning("Cache index revision read failed: %s", type(error).__name__)
        return None


def bump_index_revision(store: KeyValueStore | None, settings: CacheSettings) -> int | None:
    """Bump the shared Redis revision counter on alias release or rollback."""
    if store is None or not settings.enabled:
        return None
    try:
        return store.incr(index_revision_key(settings.key_prefix), settings.index_revision_ttl_s)
    except Exception as error:
        logger.warning("Cache index revision bump failed: %s", type(error).__name__)
        return None


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


class CachedEmbedder:
    """Layer 1: content-addressed embedding cache keyed by model profile and normalised text."""

    def __init__(
        self,
        inner: Embedder,
        store: KeyValueStore | None,
        retrieval_settings: RetrievalSettings,
        cache_settings: CacheSettings,
        *,
        observer: object | None = None,
    ) -> None:
        self.inner = inner
        self.store = store
        self.retrieval_settings = retrieval_settings
        self.cache_settings = cache_settings
        self.observer = observer

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if (
            self.store is None
            or not self.cache_settings.enabled
            or not self.cache_settings.embedding.enabled
        ):
            return self.inner.embed(texts)

        keys = [
            embedding_cache_key(self.cache_settings.key_prefix, self.retrieval_settings, text)
            for text in texts
        ]
        results: list[list[float] | None] = [None] * len(texts)
        missing_indices: list[int] = []

        for index, key in enumerate(keys):
            vector = self._read_vector(key)
            if vector is not None:
                results[index] = vector
                record_cache_event("embedding", "hit", observer=self.observer)
            else:
                missing_indices.append(index)

        if missing_indices:
            computed = self.inner.embed([texts[index] for index in missing_indices])
            if len(computed) != len(missing_indices):
                raise ValueError("Inner embedder returned the wrong number of vectors")
            for index, vector in zip(missing_indices, computed, strict=True):
                results[index] = vector
                self._write_vector(keys[index], vector)

        return [vector for vector in results if vector is not None]

    def _read_vector(self, key: str) -> list[float] | None:
        assert self.store is not None
        try:
            raw = self.store.get(key)
        except Exception as error:
            logger.warning("Embedding cache read failed: %s", type(error).__name__)
            record_cache_event("embedding", "error", observer=self.observer, reason="read_error")
            return None
        if raw is None:
            record_cache_event("embedding", "miss", observer=self.observer)
            return None
        try:
            parsed = json.loads(raw)
            if (
                isinstance(parsed, list)
                and len(parsed) == self.retrieval_settings.embedding_dim
                and all(isinstance(v, (int, float)) and math.isfinite(float(v)) for v in parsed)
            ):
                return [float(v) for v in parsed]
        except Exception as error:
            logger.warning("Embedding cache decode failed: %s", type(error).__name__)
        record_cache_event("embedding", "error", observer=self.observer, reason="decode_error")
        return None

    def _write_vector(self, key: str, vector: list[float]) -> None:
        assert self.store is not None
        try:
            self.store.set(
                key,
                json.dumps(vector, separators=(",", ":")),
                self.cache_settings.embedding.ttl_s,
            )
        except Exception as error:
            logger.warning("Embedding cache write failed: %s", type(error).__name__)
            record_cache_event("embedding", "error", observer=self.observer, reason="write_error")


class CachedRetriever:
    """Layer 2: versioned retrieval cache keyed by query, filters, build revision, and config."""

    def __init__(
        self,
        inner: Retriever,
        store: KeyValueStore | None,
        build_id_provider: Callable[[], str | None],
        retrieval_settings: RetrievalSettings,
        cache_settings: CacheSettings,
        *,
        observer: object | None = None,
    ) -> None:
        self.inner = inner
        self.store = store
        self.build_id_provider = build_id_provider
        self.retrieval_settings = retrieval_settings
        self.cache_settings = cache_settings
        self.observer = observer
        self._cfg_hash = retrieval_config_hash(retrieval_settings)

    def supports_filters(self) -> bool:
        return supports_filters(self.inner)

    def filter_scope(self) -> AbstractContextManager[None]:
        return filter_scope(self.inner)

    def retrieve(
        self, query: str, top_k: int, filters: RetrievalFilters | None = None
    ) -> list[RetrievedChunk]:
        if (
            self.store is None
            or not self.cache_settings.enabled
            or not self.cache_settings.retrieval.enabled
        ):
            return self._inner_retrieve(query, top_k, filters)

        build_rev = build_revision(
            self.build_id_provider(), current_index_revision(self.store, self.cache_settings)
        )
        if build_rev is None:
            record_cache_event("retrieval", "bypass", observer=self.observer, reason="no_build_id")
            return self._inner_retrieve(query, top_k, filters)

        key = retrieval_cache_key(
            self.cache_settings.key_prefix,
            query,
            filters,
            top_k,
            build_rev,
            self._cfg_hash,
        )
        cached = self._read_chunks(key)
        if cached is not None:
            record_cache_event("retrieval", "hit", observer=self.observer)
            return cached

        chunks = self._inner_retrieve(query, top_k, filters)
        self._write_chunks(key, chunks)
        return chunks

    def _inner_retrieve(
        self, query: str, top_k: int, filters: RetrievalFilters | None
    ) -> list[RetrievedChunk]:
        if filters is None:
            return self.inner.retrieve(query, top_k)
        return self.inner.retrieve(query, top_k, filters=filters)

    def _read_chunks(self, key: str) -> list[RetrievedChunk] | None:
        assert self.store is not None
        try:
            raw = self.store.get(key)
        except Exception as error:
            logger.warning("Retrieval cache read failed: %s", type(error).__name__)
            record_cache_event("retrieval", "error", observer=self.observer, reason="read_error")
            return None
        if raw is None:
            record_cache_event("retrieval", "miss", observer=self.observer)
            return None
        try:
            payload = json.loads(raw)
            if isinstance(payload, list):
                return [RetrievedChunk.model_validate(item) for item in payload]
        except Exception as error:
            logger.warning("Retrieval cache decode failed: %s", type(error).__name__)
        record_cache_event("retrieval", "error", observer=self.observer, reason="decode_error")
        return None

    def _write_chunks(self, key: str, chunks: list[RetrievedChunk]) -> None:
        assert self.store is not None
        try:
            payload = json.dumps(
                [chunk.model_dump(mode="json") for chunk in chunks],
                separators=(",", ":"),
                ensure_ascii=False,
            )
            self.store.set(key, payload, self.cache_settings.retrieval.ttl_s)
        except Exception as error:
            logger.warning("Retrieval cache write failed: %s", type(error).__name__)
            record_cache_event("retrieval", "error", observer=self.observer, reason="write_error")


class CachedAnswer(BaseModel):
    answer: str
    citations: list[CitationRecord] = Field(default_factory=list)
    retrieval: list[RetrievedChunk] = Field(default_factory=list)
    gate: GateResult
    coverage: CoverageAnswer | None = None
    claims: list[ClaimAssessment] | None = None
    claims_removed: int = 0
    filters_applied: bool = False
    retrieval_build_id: str
    models: dict[str, str] = Field(default_factory=dict)


class AnswerCache:
    """Layer 3: versioned exact (and optional near-duplicate) knowledge answer cache."""

    def __init__(
        self,
        store: KeyValueStore | None,
        cache_settings: CacheSettings,
        *,
        embedder: Embedder | None = None,
        observer: object | None = None,
    ) -> None:
        self.store = store
        self.settings = cache_settings
        self.embedder = embedder
        self.observer = observer

    def get(
        self,
        *,
        query: str,
        filters: RetrievalFilters | None,
        build_id: str | None,
        prompt_version: str,
        models: Mapping[str, str],
    ) -> tuple[CachedAnswer | None, CacheLayer | None]:
        if self.store is None or not self.settings.enabled or not self.settings.answer.enabled:
            return None, None
        build_rev = build_revision(build_id, current_index_revision(self.store, self.settings))
        if build_rev is None:
            record_cache_event("answer", "bypass", observer=self.observer, reason="no_build_id")
            return None, None

        exact_key = answer_cache_key(
            self.settings.key_prefix, query, filters, build_rev, prompt_version, models
        )
        entry = self._read_answer(exact_key, layer="answer")
        if entry is not None:
            record_cache_event("answer", "hit", observer=self.observer)
            return entry, "answer"

        if self.settings.answer.near_duplicate.enabled and self.embedder is not None:
            semantic_entry = self._semantic_lookup(
                query=query,
                filters=filters,
                build_rev=build_rev,
                prompt_version=prompt_version,
                models=models,
            )
            if semantic_entry is not None:
                record_cache_event("answer_semantic", "hit", observer=self.observer)
                return semantic_entry, "answer_semantic"
            record_cache_event("answer_semantic", "miss", observer=self.observer)

        return None, None

    def set(
        self,
        *,
        query: str,
        filters: RetrievalFilters | None,
        build_id: str | None,
        prompt_version: str,
        models: Mapping[str, str],
        entry: CachedAnswer,
    ) -> bool:
        if self.store is None or not self.settings.enabled or not self.settings.answer.enabled:
            return False
        build_rev = build_revision(build_id, current_index_revision(self.store, self.settings))
        if build_rev is None:
            return False

        exact_key = answer_cache_key(
            self.settings.key_prefix, query, filters, build_rev, prompt_version, models
        )
        try:
            self.store.set(
                exact_key,
                entry.model_dump_json(),
                self.settings.answer.ttl_s,
            )
        except Exception as error:
            logger.warning("Answer cache write failed: %s", type(error).__name__)
            record_cache_event("answer", "error", observer=self.observer, reason="write_error")
            return False

        if self.settings.answer.near_duplicate.enabled and self.embedder is not None:
            self._write_bucket_entry(
                exact_key=exact_key,
                query=query,
                filters=filters,
                build_rev=build_rev,
                prompt_version=prompt_version,
                models=models,
            )
        return True

    def _read_answer(self, key: str, *, layer: CacheLayer) -> CachedAnswer | None:
        assert self.store is not None
        try:
            raw = self.store.get(key)
        except Exception as error:
            logger.warning("Answer cache read failed: %s", type(error).__name__)
            record_cache_event(layer, "error", observer=self.observer, reason="read_error")
            return None
        if raw is None:
            if layer == "answer":
                record_cache_event("answer", "miss", observer=self.observer)
            return None
        try:
            return CachedAnswer.model_validate_json(raw)
        except Exception as error:
            logger.warning("Answer cache decode failed: %s", type(error).__name__)
            record_cache_event(layer, "error", observer=self.observer, reason="decode_error")
            return None

    def _semantic_lookup(
        self,
        *,
        query: str,
        filters: RetrievalFilters | None,
        build_rev: str,
        prompt_version: str,
        models: Mapping[str, str],
    ) -> CachedAnswer | None:
        assert self.store is not None and self.embedder is not None
        bucket = answer_bucket_key(
            self.settings.key_prefix, filters, build_rev, prompt_version, models
        )
        try:
            raw = self.store.get(bucket)
        except Exception as error:
            logger.warning("Semantic cache bucket read failed: %s", type(error).__name__)
            record_cache_event(
                "answer_semantic", "error", observer=self.observer, reason="read_error"
            )
            return None
        if not raw:
            return None
        try:
            items: list[dict[str, Any]] = json.loads(raw)
            query_vec = self.embedder.embed([normalise_query_text(query)])[0]
        except Exception as error:
            logger.warning("Semantic cache lookup failed: %s", type(error).__name__)
            record_cache_event(
                "answer_semantic", "error", observer=self.observer, reason="embed_error"
            )
            return None

        best_key: str | None = None
        best_score = -1.0
        threshold = self.settings.answer.near_duplicate.similarity_threshold
        for item in items:
            candidate_key = item.get("key")
            candidate_vec = item.get("embedding")
            if not isinstance(candidate_key, str) or not isinstance(candidate_vec, list):
                continue
            score = _cosine_similarity(query_vec, candidate_vec)
            if score >= threshold and score > best_score:
                best_score = score
                best_key = candidate_key
        if best_key is None:
            return None
        return self._read_answer(best_key, layer="answer_semantic")

    def _write_bucket_entry(
        self,
        *,
        exact_key: str,
        query: str,
        filters: RetrievalFilters | None,
        build_rev: str,
        prompt_version: str,
        models: Mapping[str, str],
    ) -> None:
        assert self.store is not None and self.embedder is not None
        bucket = answer_bucket_key(
            self.settings.key_prefix, filters, build_rev, prompt_version, models
        )
        try:
            query_vec = self.embedder.embed([normalise_query_text(query)])[0]
            raw = self.store.get(bucket)
            items: list[dict[str, Any]] = json.loads(raw) if raw else []
            items = [item for item in items if item.get("key") != exact_key]
            items.append({"key": exact_key, "embedding": query_vec})
            cap = self.settings.answer.near_duplicate.max_entries_per_bucket
            if len(items) > cap:
                items = items[-cap:]
            self.store.set(
                bucket,
                json.dumps(items, separators=(",", ":")),
                self.settings.answer.ttl_s,
            )
        except Exception as error:
            logger.warning("Semantic cache bucket write failed: %s", type(error).__name__)
            record_cache_event(
                "answer_semantic", "error", observer=self.observer, reason="write_error"
            )
