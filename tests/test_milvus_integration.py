from __future__ import annotations

from uuid import uuid4

import pytest

from support_agent.config import get_settings
from support_agent.retrieval.chunking import Chunk
from support_agent.retrieval.embed import FakeEmbedder
from support_agent.retrieval.factory import build_retriever
from support_agent.retrieval.milvus_store import MilvusStore


@pytest.mark.integration
def test_dense_and_bm25_roundtrip_in_temporary_collection() -> None:
    settings = get_settings().model_copy(deep=True)
    settings.milvus.collection = "support_chunks_it_" + uuid4().hex
    texts = [
        "Orchid care instructions.",
        "Violet return policy.",
        "Cactus shipping details.",
        "Rose payment methods.",
        "Tulip membership conditions.",
    ]
    chunks = [
        Chunk(
            chunk_id=f"fixture-{index}",
            doc_id="fixture",
            section_id=f"fixture.{index}",
            title="Fixture",
            heading_path=f"Fixture > {index}",
            text=text,
            n_tokens=len(text.split()),
        )
        for index, text in enumerate(texts)
    ]
    vectors = FakeEmbedder(settings.retrieval.embedding_dim).embed(texts)
    store = MilvusStore(settings)
    try:
        store.create_or_reset()
        store.upsert(chunks, vectors)
        assert store.count() == len(texts)
        assert store.search_dense(vectors[1], limit=len(texts))[0].chunk_id == chunks[1].chunk_id
        lexical = store.search_bm25("violet", limit=len(texts))
        assert lexical and lexical[0].chunk_id == chunks[1].chunk_id
        assert lexical[0].section_id == chunks[1].section_id
        assert lexical[0].title == chunks[1].title
        assert lexical[0].n_tokens == chunks[1].n_tokens
        assert sorted(store.read_chunks(), key=lambda c: c.chunk_id) == sorted(
            chunks, key=lambda c: c.chunk_id
        )
        store.use_chunk_snapshot(chunks)
        hydrated = store.search_bm25("violet", limit=len(texts))
        assert hydrated == lexical
        retriever = build_retriever(
            "hybrid",
            settings=settings,
            store=store,
            embedder=FakeEmbedder(settings.retrieval.embedding_dim),
        )
        fused = retriever.retrieve(texts[1], top_k=len(texts))
        assert fused[0].chunk_id == chunks[1].chunk_id
        assert fused[0].ranks == {"dense": 1, "bm25": 1}
        assert fused[0].scores["rrf"] == pytest.approx(2 / (settings.retrieval.rrf_k + 1))
        store.upsert(chunks, vectors)
        assert store.count() == len(texts)
    finally:
        store.drop()
        store.close()
