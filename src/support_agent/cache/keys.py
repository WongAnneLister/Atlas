"""Pure, deterministic cache key builders and version hashes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from support_agent.config import RetrievalSettings, Settings
from support_agent.retrieval.filters import RetrievalFilters

_ANSWER_PROMPT_FILES = (
    "answer.md",
    "answer_parts.md",
    "verify_claims.md",
    "split_claims.md",
)


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def normalise_embedding_text(text: str) -> str:
    """Collapse whitespace while preserving case and model-number punctuation."""
    return " ".join(text.split())


def normalise_query_text(text: str) -> str:
    """Normalise a rewritten query for exact/semantic cache lookup."""
    collapsed = " ".join(text.strip().lower().split())
    return collapsed.rstrip("?!.").strip()


def serialise_filters(filters: RetrievalFilters | None) -> dict[str, str | None]:
    if filters is None:
        return {"as_of": None, "product_category": None}
    return {
        "as_of": filters.as_of.isoformat() if filters.as_of is not None else None,
        "product_category": filters.product_category,
    }


def embedding_profile_hash(settings: RetrievalSettings) -> str:
    return _canonical_sha256(
        {
            "embedding_model": settings.embedding_model,
            "embedding_revision": settings.embedding_revision,
            "embedding_dim": settings.embedding_dim,
            "embedding_normalize": settings.embedding_normalize,
            "embedding_max_tokens": settings.embedding_max_tokens,
            "embedding_window_tokens": settings.embedding_window_tokens,
        }
    )


def embedding_cache_key(prefix: str, settings: RetrievalSettings, text: str) -> str:
    digest = _canonical_sha256(
        {
            "profile": embedding_profile_hash(settings),
            "text": normalise_embedding_text(text),
        }
    )
    return f"{prefix}:emb:{digest}"


def retrieval_config_hash(settings: RetrievalSettings) -> str:
    return _canonical_sha256(
        {
            "embedding_profile": embedding_profile_hash(settings),
            "reranker_model": settings.reranker_model,
            "reranker_revision": settings.reranker_revision,
            "reranker_max_tokens": settings.reranker_max_tokens,
            "rerank_candidates_k": settings.rerank_candidates_k,
            "dense_top_k": settings.dense_top_k,
            "bm25_top_k": settings.bm25_top_k,
            "bm25_normalise_model_numbers": settings.bm25_normalise_model_numbers,
            "rrf_k": settings.rrf_k,
            "rerank_top_k": settings.rerank_top_k,
            "dedupe_text": settings.dedupe_text,
            "store_scope": settings.store_scope.model_dump(mode="json"),
            "filters": settings.filters.model_dump(mode="json"),
        }
    )


def build_revision(build_id: str | None, alias_revision: str | None = None) -> str | None:
    """Combine Milvus build id with an optional Redis alias revision counter."""
    if not build_id or not build_id.strip():
        return None
    clean_id = build_id.strip()
    if alias_revision and alias_revision.strip():
        return f"{clean_id}:r{alias_revision.strip()}"
    return clean_id


def index_revision_key(prefix: str) -> str:
    return f"{prefix}:index_rev"


def retrieval_cache_key(
    prefix: str,
    query: str,
    filters: RetrievalFilters | None,
    top_k: int,
    build_rev: str,
    retrieval_cfg_hash: str,
) -> str:
    digest = _canonical_sha256(
        {
            "query": normalise_query_text(query),
            "filters": serialise_filters(filters),
            "top_k": top_k,
            "build_rev": build_rev,
            "retrieval_config_hash": retrieval_cfg_hash,
        }
    )
    return f"{prefix}:ret:{digest}"


def prompt_version_hash(prompts_dir: Path, settings: Settings) -> str:
    prompts: dict[str, str] = {}
    for name in _ANSWER_PROMPT_FILES:
        path = prompts_dir / name
        if path.exists():
            prompts[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return _canonical_sha256(
        {
            "prompts": prompts,
            "gate": settings.gate.model_dump(mode="json"),
            "grounding": settings.grounding.model_dump(mode="json"),
            "knowledge": settings.knowledge.model_dump(mode="json"),
            "rerank_top_k": settings.retrieval.rerank_top_k,
            "store_scope": settings.retrieval.store_scope.model_dump(mode="json"),
        }
    )


def answer_bucket_key(
    prefix: str,
    filters: RetrievalFilters | None,
    build_rev: str,
    prompt_version: str,
    models: Mapping[str, str],
) -> str:
    digest = _canonical_sha256(
        {
            "filters": serialise_filters(filters),
            "build_rev": build_rev,
            "prompt_version": prompt_version,
            "models": dict(sorted(models.items())),
        }
    )
    return f"{prefix}:ans_bucket:{digest}"


def answer_cache_key(
    prefix: str,
    query: str,
    filters: RetrievalFilters | None,
    build_rev: str,
    prompt_version: str,
    models: Mapping[str, str],
) -> str:
    digest = _canonical_sha256(
        {
            "query": normalise_query_text(query),
            "filters": serialise_filters(filters),
            "build_rev": build_rev,
            "prompt_version": prompt_version,
            "models": dict(sorted(models.items())),
        }
    )
    return f"{prefix}:ans:{digest}"
