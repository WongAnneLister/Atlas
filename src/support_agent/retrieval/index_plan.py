"""Compare source sections against the currently serving build."""

from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, JsonValue

from support_agent.config import REPO_ROOT, Settings
from support_agent.data.doc_models import digest, json_text
from support_agent.data.section_metadata import load_section_metadata, require_section_metadata
from support_agent.data.validate_docs import SECTION, parse_document
from support_agent.retrieval.chunking import CHUNKER_VERSION, Chunk, chunk_section
from support_agent.retrieval.index_models import (
    BuildRecord,
    BuildSection,
    Corpus,
    SourceDocument,
    SourceSection,
)
from support_agent.retrieval.milvus_store import STORE_SCHEMA_VERSION
from support_agent.retrieval.tokenization import Tokenizer

_EMBEDDING_FIELDS = {
    "embedding_model",
    "embedding_revision",
    "embedding_dim",
    "embedding_normalize",
    "embedding_max_tokens",
    "embedding_window_tokens",
    "embedding_use_fp16",
}
_SCHEMA_FIELDS = {
    "analyzer",
    "id_max_bytes",
    "section_max_bytes",
    "heading_max_bytes",
    "text_max_bytes",
    "hnsw_m",
    "hnsw_ef_construction",
    "sparse_algorithm",
    "bm25_b",
    "bm25_k1",
}


class IndexPlan(BaseModel):
    added: list[str]
    changed: list[str]
    deleted: list[str]
    unchanged: list[str]
    docs_hash: str
    fingerprint: str
    live_fingerprint: str | None
    mode: Literal["incremental", "full"]


def embedding_profile(settings: Settings) -> dict[str, JsonValue]:
    return settings.retrieval.model_dump(mode="json", include=_EMBEDDING_FIELDS)


def index_fingerprint(settings: Settings, *, legacy_schema: bool = False) -> str:
    schema = settings.milvus.model_dump(mode="json", include=_SCHEMA_FIELDS)
    if not legacy_schema:
        schema["metadata_max_bytes"] = settings.milvus.metadata_max_bytes
        schema["open_end_day"] = settings.policy_versions.open_end_day
    return digest(
        json_text(
            {
                "embedding": embedding_profile(settings),
                "chunk": settings.chunk.model_dump(mode="json"),
                "index_schema": schema,
                "chunker_version": CHUNKER_VERSION,
                "store_schema_version": "1" if legacy_schema else STORE_SCHEMA_VERSION,
            }
        )
    )


def load_corpus(docs_dir: Path) -> Corpus:
    metadata = load_section_metadata(docs_dir)
    documents: dict[str, SourceDocument] = {}
    sections: dict[str, SourceSection] = {}
    for path in sorted(docs_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        parsed, header = parse_document(text)
        if header.doc_id in documents or sections.keys() & parsed.keys():
            raise ValueError("Duplicate document or section id")
        doc = SourceDocument(
            doc_id=header.doc_id, title=header.title, source=header.source_datasets
        )
        documents[doc.doc_id] = doc
        headings = {match[2].strip(): match[1].strip() for match in SECTION.finditer(text)}
        for sid, prose in parsed.items():
            section_metadata = require_section_metadata(metadata, sid)
            fields = {"doc_id": doc.doc_id, "heading": headings[sid], "text": prose}
            sections[sid] = SourceSection(
                section_id=sid,
                content_hash=digest(
                    json_text(
                        {
                            **fields,
                            "title": doc.title,
                            "metadata": section_metadata.model_dump(mode="json"),
                        }
                    )
                ),
                metadata=section_metadata,
                **fields,
            )
    if not sections:
        raise ValueError("No source documents or sections")
    if sections.keys() != metadata.keys():
        raise ValueError("Section metadata contains sections outside the source documents")
    identity = json_text(
        {
            "documents": {key: doc.model_dump() for key, doc in documents.items()},
            "sections": {key: section.content_hash for key, section in sections.items()},
        }
    )
    return Corpus(documents=documents, sections=sections, docs_hash=digest(identity))


def plan_index(
    corpus: Corpus,
    live: BuildRecord | None,
    snapshots: Mapping[str, BuildSection],
    settings: Settings,
    *,
    force_full: bool = False,
) -> IndexPlan:
    existing = snapshots if live is not None else {}
    fingerprint = index_fingerprint(settings)
    live_fingerprint = live.fingerprint if live else None
    common = corpus.sections.keys() & existing.keys()
    changed = {
        sid for sid in common if corpus.sections[sid].content_hash != existing[sid].content_hash
    }
    return IndexPlan(
        added=sorted(corpus.sections.keys() - existing.keys()),
        changed=sorted(changed),
        deleted=sorted(existing.keys() - corpus.sections.keys()),
        unchanged=sorted(common - changed),
        docs_hash=corpus.docs_hash,
        fingerprint=fingerprint,
        live_fingerprint=live_fingerprint,
        mode="incremental" if not force_full and fingerprint == live_fingerprint else "full",
    )


def default_docs_dir(settings: Settings) -> Path:
    return REPO_ROOT / settings.data.processed_dir / "docs"


def chunks_for(
    corpus: Corpus, section_ids: list[str], settings: Settings, tokenizer: Tokenizer
) -> list[Chunk]:
    return [
        chunk
        for sid in section_ids
        for chunk in chunk_section(
            sid,
            corpus.sections[sid].text,
            corpus.documents[corpus.sections[sid].doc_id].doc_id,
            corpus.documents[corpus.sections[sid].doc_id].title,
            corpus.sections[sid].heading,
            settings.chunk,
            tokenizer,
            metadata=corpus.sections[sid].metadata,
        )
    ]
