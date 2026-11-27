"""Build and release an index, or prepare preview chunks without Milvus."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime
from importlib import import_module
from time import perf_counter

from pydantic import BaseModel, Field

from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.data.doc_models import digest, json_text, write_text
from support_agent.retrieval.chunking import (
    Chunk,
    ChunkSizeStats,
    chunk_size_stats,
    embedding_text,
    load_chunks,
)
from support_agent.retrieval.embed import BgeM3Embedder, Embedder
from support_agent.retrieval.index_plan import default_docs_dir, load_corpus
from support_agent.retrieval.milvus_store import ChunkStore, MilvusStore
from support_agent.retrieval.tokenization import BgeTokenizer, Tokenizer

log = logging.getLogger(__name__)


class IngestRun(BaseModel):
    build_id: str | None = None
    started_at: str
    status: str = "preparing"
    config_hash: str
    corpus_hash: str = ""
    chunk_hash: str = ""
    tokenizer: str
    embedding_model: str
    embedding_revision: str
    policy_max_tokens: int
    policy_overlap_tokens: int
    prepend_heading: bool
    encoder_window_tokens: int
    embedding_windows: int = 0
    chunk_count: int = 0
    chunk_sizes: ChunkSizeStats | None = None
    stored_count: int | None = None
    server_version: str | None = None
    timings_s: dict[str, float] = Field(default_factory=dict)
    error: str | None = None


def prepare_chunks(settings: Settings, tokenizer: Tokenizer) -> list[Chunk]:
    return load_chunks(REPO_ROOT / settings.data.processed_dir / "docs", settings.chunk, tokenizer)


def ingest_chunks(
    chunks: list[Chunk],
    embedder: Embedder,
    store: ChunkStore,
    settings: Settings,
) -> int:
    vectors = embedder.embed([embedding_text(chunk, settings.chunk) for chunk in chunks])
    if len(vectors) != len(chunks):
        raise ValueError("Embedder returned the wrong number of vectors")
    if isinstance(store, MilvusStore):
        store.validate(chunks, vectors)  # Check all rows before replacing the existing collection.
    store.create_or_reset()
    store.upsert(chunks, vectors)
    count = store.count()
    if count != len(chunks):
        raise RuntimeError(f"Stored count {count} differs from chunk count {len(chunks)}")
    return count


def run(settings: Settings, *, chunks_only: bool = False) -> IngestRun:
    output = REPO_ROOT / settings.data.processed_dir
    if chunks_only:
        output /= settings.index.preview_directory
    run_info = IngestRun(
        started_at=datetime.now(UTC).isoformat(),
        config_hash=digest(json_text(settings.model_dump(mode="json"))),
        tokenizer=settings.retrieval.embedding_model,
        embedding_model=settings.retrieval.embedding_model,
        embedding_revision=settings.retrieval.embedding_revision,
        policy_max_tokens=settings.chunk.max_tokens,
        policy_overlap_tokens=settings.chunk.overlap_tokens,
        prepend_heading=settings.chunk.prepend_heading,
        encoder_window_tokens=settings.retrieval.embedding_window_tokens,
    )
    store: MilvusStore | None = None
    started = perf_counter()
    try:
        tokenizer = BgeTokenizer(settings.retrieval)
        chunks = prepare_chunks(settings, tokenizer)
        text = "".join(chunk.model_dump_json() + "\n" for chunk in chunks)
        write_text(output / "chunks.jsonl", text)
        run_info.chunk_count = len(chunks)
        run_info.chunk_sizes = chunk_size_stats(chunks, settings.chunk)
        run_info.chunk_hash = digest(text)
        run_info.corpus_hash = load_corpus(default_docs_dir(settings)).docs_hash
        run_info.timings_s["chunking"] = perf_counter() - started
        if chunks_only:
            run_info.status = "chunks_only"
        else:
            # Test connectivity before downloading or loading model weights.
            store = MilvusStore(settings)
            run_info.server_version = store.server_version()
            embedder = BgeM3Embedder(settings.retrieval, tokenizer)
            embedding_started = perf_counter()
            run_info.stored_count = ingest_chunks(chunks, embedder, store, settings)
            run_info.embedding_windows = embedder.window_count
            run_info.timings_s["embedding_and_ingestion"] = perf_counter() - embedding_started
            run_info.status = "complete"
    except Exception as exc:
        run_info.status, run_info.error = "failed", f"{type(exc).__name__}: {exc}"
        raise
    finally:
        run_info.timings_s["total"] = perf_counter() - started
        write_text(output / "ingest_run.json", run_info.model_dump_json(indent=2) + "\n")
        if store is not None:
            store.close()
        log.info(
            "ingest status=%s chunks=%d stored=%s timings=%s",
            run_info.status,
            run_info.chunk_count,
            run_info.stored_count,
            run_info.timings_s,
        )
    return run_info


def main() -> int:
    if "--chunks-only" not in sys.argv[1:]:
        lifecycle = import_module("eval.index_lifecycle")
        return int(lifecycle.main(["ingest", *sys.argv[1:]]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunks-only", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        run(get_settings(), chunks_only=args.chunks_only)
    except Exception as exc:
        log.error("ingestion failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
