"""Build a complete private collection, reusing unchanged stored vectors."""

import json
import logging
import struct
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import perf_counter
from uuid import uuid4

from pydantic import BaseModel

from support_agent.config import REPO_ROOT, Settings
from support_agent.data.doc_models import digest, json_text
from support_agent.retrieval.chunking import CHUNKER_VERSION, Chunk, embedding_text
from support_agent.retrieval.embed import BgeM3Embedder, Embedder
from support_agent.retrieval.index_models import BuildMode, BuildRecord, Corpus
from support_agent.retrieval.index_plan import (
    chunks_for,
    default_docs_dir,
    embedding_profile,
    load_corpus,
    plan_index,
)
from support_agent.retrieval.index_snapshot import Snapshot, build_snapshot_path
from support_agent.retrieval.milvus_store import MilvusStore, VectorChunk
from support_agent.retrieval.registry import IndexRegistry
from support_agent.retrieval.tokenization import BgeTokenizer, Tokenizer

logger = logging.getLogger(__name__)


class BuildResult(BaseModel):
    build_id: str
    collection: str
    mode: BuildMode
    embedded_chunks: int
    copied_chunks: int
    chunk_count: int
    elapsed_s: float
    docs_hash: str


def store_for(settings: Settings, collection: str) -> MilvusStore:
    config = settings.model_copy(deep=True)
    config.milvus.collection = collection
    return MilvusStore(config)


def new_build(
    settings: Settings,
    corpus: Corpus,
    fingerprint: str,
    *,
    mode: BuildMode,
    parent_build_id: str | None = None,
    collection: str | None = None,
) -> BuildRecord:
    ident = uuid4().hex
    return BuildRecord(
        build_id=ident,
        collection=collection or f"{settings.index.collection_prefix}{ident}",
        mode=mode,
        fingerprint=fingerprint,
        embed_model=settings.retrieval.embedding_model,
        embed_revision=settings.retrieval.embedding_revision,
        embedding_profile=embedding_profile(settings),
        chunker_version=CHUNKER_VERSION,
        docs_hash=corpus.docs_hash,
        parent_build_id=parent_build_id,
    )


def _copy_rows(
    make_store: Callable[[str], MilvusStore],
    live: BuildRecord,
    section_ids: list[str],
    counts: dict[str, int],
) -> list[VectorChunk]:
    if not section_ids:
        return []
    source = make_store(live.collection)
    try:
        rows = source.read_vectors(section_ids)
    finally:
        source.close()
    if Counter(row.chunk.section_id for row in rows) != {sid: counts[sid] for sid in section_ids}:
        raise ValueError("Live collection does not match its unchanged section snapshot")
    if len({row.chunk.chunk_id for row in rows}) != len(rows):
        raise ValueError("Live collection returned duplicate chunk IDs")
    return rows


def _vector_bytes(values: list[float]) -> bytes:
    return struct.pack(f"<{len(values)}f", *values)


def _verify(
    store: MilvusStore, chunks: list[Chunk], copied: list[VectorChunk], deleted: set[str]
) -> None:
    if store.count() != len(chunks):
        raise ValueError("Candidate row count differs from its source chunks")
    actual = {chunk.chunk_id: chunk for chunk in store.read_chunks()}
    if actual != {chunk.chunk_id: chunk for chunk in chunks} or any(
        chunk.section_id in deleted for chunk in actual.values()
    ):
        raise ValueError("Candidate chunk snapshot differs from its source")
    if copied:
        rows = store.read_vectors(sorted({row.chunk.section_id for row in copied}))
        got = {row.chunk.chunk_id: _vector_bytes(row.dense) for row in rows}
        if got != {row.chunk.chunk_id: _vector_bytes(row.dense) for row in copied}:
            raise ValueError("Candidate did not preserve unchanged dense vectors")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(content)
            handle.flush()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def _chunk_text(chunks: list[Chunk]) -> str:
    return "".join(chunk.model_dump_json() + "\n" for chunk in chunks)


def save_build_snapshot(settings: Settings, build_id: str, chunks: list[Chunk]) -> None:
    output = build_snapshot_path(settings, build_id)
    text = _chunk_text(chunks)
    _atomic_write(output / "chunks.jsonl", text)
    manifest = Snapshot(build_id=build_id, chunk_hash=digest(text))
    _atomic_write(output / "snapshot.json", manifest.model_dump_json() + "\n")


def _save_latest(settings: Settings, result: BuildResult, chunks: list[Chunk]) -> None:
    text = _chunk_text(chunks)
    output = REPO_ROOT / settings.data.processed_dir
    _atomic_write(output / "chunks.jsonl", text)
    _atomic_write(
        output / "ingest_run.json",
        json.dumps(
            {
                **result.model_dump(),
                "status": "complete",
                "started_at": datetime.now(UTC).isoformat(),
                "config_hash": digest(json_text(settings.model_dump(mode="json"))),
                "corpus_hash": result.docs_hash,
                "chunk_hash": digest(text),
                "tokenizer": settings.retrieval.embedding_model,
                "embedding_model": settings.retrieval.embedding_model,
                "embedding_revision": settings.retrieval.embedding_revision,
                "policy_max_tokens": settings.chunk.max_tokens,
                "policy_overlap_tokens": settings.chunk.overlap_tokens,
                "prepend_heading": settings.chunk.prepend_heading,
                "encoder_window_tokens": settings.retrieval.embedding_window_tokens,
                "stored_count": result.chunk_count,
                "timings_s": {"total": result.elapsed_s},
            },
            indent=2,
        )
        + "\n",
    )


def build_index(
    settings: Settings,
    registry: IndexRegistry,
    *,
    docs_dir: Path | None = None,
    tokenizer: Tokenizer | None = None,
    embedder: Embedder | None = None,
    make_store: Callable[[str], MilvusStore] | None = None,
    force_full: bool = False,
) -> BuildResult:
    started = perf_counter()

    def collection_store(collection: str) -> MilvusStore:
        return store_for(settings, collection) if make_store is None else make_store(collection)

    corpus = load_corpus(docs_dir or default_docs_dir(settings))
    registry.initialize()
    alias = registry.get_alias(settings.index.live_alias)
    live = registry.get_build(alias.build_id)
    previous = registry.build_sections(live.build_id) if live else {}
    plan = plan_index(corpus, live, previous, settings, force_full=force_full)
    record = new_build(
        settings, corpus, plan.fingerprint, mode=plan.mode, parent_build_id=alias.build_id
    )
    registry.begin_build(record)
    target: MilvusStore | None = None
    created = False
    try:
        active_tokenizer = tokenizer or BgeTokenizer(settings.retrieval)
        copy_ids = plan.unchanged if live and plan.mode == "incremental" else []
        copied = (
            _copy_rows(
                collection_store,
                live,
                copy_ids,
                {sid: section.chunk_count for sid, section in previous.items()},
            )
            if live
            else []
        )
        changed = chunks_for(
            corpus, sorted(corpus.sections.keys() - set(copy_ids)), settings, active_tokenizer
        )
        vectors = []
        if changed:
            model = embedder or BgeM3Embedder(settings.retrieval, active_tokenizer)
            vectors = model.embed([embedding_text(chunk, settings.chunk) for chunk in changed])
        chunks = [*changed, *(row.chunk for row in copied)]
        target = collection_store(record.collection)
        target.validate(chunks, [*vectors, *(row.dense for row in copied)])
        target.create()
        created = True
        target.upsert(chunks, [*vectors, *(row.dense for row in copied)])
        _verify(target, chunks, copied, set(plan.deleted))
        save_build_snapshot(settings, record.build_id, chunks)
        registry.finish_build(
            record.build_id,
            corpus,
            Counter(chunk.section_id for chunk in chunks),
            deleted=plan.deleted,
        )
    except Exception:
        try:
            if created and target is not None:
                target.drop()
        finally:
            registry.fail_build(record.build_id)
        raise
    finally:
        if target is not None:
            target.close()
    result = BuildResult(
        build_id=record.build_id,
        collection=record.collection,
        mode=record.mode,
        embedded_chunks=len(changed),
        copied_chunks=len(copied),
        chunk_count=len(chunks),
        elapsed_s=perf_counter() - started,
        docs_hash=plan.docs_hash,
    )
    try:
        _save_latest(settings, result, chunks)
    except OSError:
        logger.exception("Build completed. The last-build snapshot could not be published.")
    return result
