"""Prepare a separate, body-only dense index for the heading-prefix ablation."""

from __future__ import annotations

import json
import logging
import platform
from importlib.metadata import version
from pathlib import Path

from pydantic import BaseModel

from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.data.doc_models import digest, json_text, write_text
from support_agent.retrieval.chunking import Chunk
from support_agent.retrieval.embed import BgeM3Embedder, Embedder
from support_agent.retrieval.index_snapshot import load_build_input
from support_agent.retrieval.milvus_store import MilvusStore

log = logging.getLogger(__name__)


def collection_for_prefix(settings: Settings, prepend_heading: bool) -> str:
    return (
        settings.retrieval_eval.baseline_collection
        if prepend_heading
        else settings.retrieval_eval.heading_ablation_collection
    )


class CachedVectors(BaseModel):
    fingerprint: str
    vectors: list[list[float]]


def inference_runtime() -> dict[str, str]:
    return {
        "platform": platform.platform(),
        **{
            name: version(name)
            for name in ("FlagEmbedding", "transformers", "torch", "tokenizers", "pymilvus")
        },
    }


def chunk_hash(chunks: list[Chunk]) -> str:
    return digest(
        json_text(
            [chunk.model_dump(mode="json") for chunk in sorted(chunks, key=lambda c: c.chunk_id)]
        )
    )


def prepare_experiment_index(
    settings: Settings,
    chunks: list[Chunk],
    embedder: Embedder,
    store: MilvusStore,
    cache_dir: Path,
    prepend_heading: bool,
) -> str:
    chunks = sorted(chunks, key=lambda chunk: chunk.chunk_id)
    if store.collection == settings.milvus.collection:
        raise ValueError("Heading ablation must never replace the baseline collection")
    expected = collection_for_prefix(settings, prepend_heading)
    if store.collection != expected or not chunks:
        raise ValueError("Expected the configured experiment collection and a nonempty corpus")
    if any(chunk.effective_from is None for chunk in chunks):
        raise ValueError("Experiment indexes require dated chunks from a metadata-enabled build")
    fields = {
        key: value
        for key, value in settings.retrieval.model_dump().items()
        if key.startswith("embedding_")
    }
    source = REPO_ROOT / "src/support_agent/retrieval"
    runtime = inference_runtime()
    vector_fingerprint = digest(
        json_text(
            {
                "chunks": chunk_hash(chunks),
                "embedding": fields,
                "prepend_heading": prepend_heading,
                "runtime": runtime,
                "builder_code": digest(Path(__file__).read_text()),
                "code": {
                    name: digest((source / name).read_text())
                    for name in ("embed.py", "chunking.py", "tokenization.py")
                },
            }
        )
    )
    fingerprint = digest(
        json_text(
            {
                "vectors": vector_fingerprint,
                "index": settings.milvus.model_dump(exclude={"uri", "collection", "timeout_s"}),
                "store_code": digest((source / "milvus_store.py").read_text()),
                "server": store.server_version(),
            }
        )
    )
    marker = cache_dir / f"index_{store.collection}.json"
    if marker.exists() and store.exists():
        saved = json.loads(marker.read_text(encoding="utf-8"))
        if (
            saved["fingerprint"] == fingerprint
            and saved["collection_id"] == store.collection_identity()
            and chunk_hash(store.read_chunks()) == chunk_hash(chunks)
        ):
            log.info("Reusing verified experiment index %s", store.collection)
            return str(saved["collection_id"])
    vector_path = cache_dir / f"vectors_{vector_fingerprint}.json"
    if vector_path.exists():
        artifact = CachedVectors.model_validate_json(vector_path.read_text())
        if artifact.fingerprint != vector_fingerprint:
            raise ValueError("Embedding cache provenance mismatch")
        vectors = artifact.vectors
        log.info("Reusing cached vectors for %s", store.collection)
    else:
        log.info(
            "Encoding %d chunks prepend_heading=%s for %s",
            len(chunks),
            prepend_heading,
            store.collection,
        )
        vectors = embedder.embed(
            [
                f"{chunk.heading_path}\n\n{chunk.text}" if prepend_heading else chunk.text
                for chunk in chunks
            ]
        )
        if len(vectors) != len(chunks):
            raise ValueError("Need one vector per source chunk")
        write_text(
            vector_path,
            CachedVectors(fingerprint=vector_fingerprint, vectors=vectors).model_dump_json(),
        )
    if isinstance(store, MilvusStore):
        store.validate(chunks, vectors)
        store.allow_experiment_writes()
    store.create_or_reset()
    store.upsert(chunks, vectors)
    if chunk_hash(store.read_chunks()) != chunk_hash(chunks):
        raise ValueError("Ablation index corpus differs from the frozen source chunks")
    identity = store.collection_identity()
    write_text(
        marker,
        json_text(
            {
                "fingerprint": fingerprint,
                "collection_id": identity,
                "vector_fingerprint": vector_fingerprint,
                "runtime": runtime,
            }
        ),
    )
    return identity


def prepare_heading_ablation(
    settings: Settings,
    chunks: list[Chunk],
    embedder: Embedder,
    store: MilvusStore,
    cache_dir: Path,
) -> str:
    return prepare_experiment_index(settings, chunks, embedder, store, cache_dir, False)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = get_settings()
    chunks = load_build_input(settings)
    embedder = BgeM3Embedder(settings.retrieval)
    for prefix, collection in [
        (True, settings.retrieval_eval.baseline_collection),
        (False, settings.retrieval_eval.heading_ablation_collection),
    ]:
        alternate = settings.model_copy(deep=True)
        alternate.milvus.collection = collection
        store = MilvusStore(alternate)
        try:
            prepare_experiment_index(
                settings,
                chunks,
                embedder,
                store,
                REPO_ROOT / settings.retrieval_eval.cache_dir,
                prefix,
            )
        finally:
            store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
