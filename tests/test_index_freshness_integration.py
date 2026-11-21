"""Real Milvus lifecycle checks using isolated names and deterministic models."""

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from eval.index_release import ReleaseDecision
from langchain_core.messages import HumanMessage
from pydantic import SecretStr
from sqlalchemy import URL
from sqlalchemy.engine import make_url

from support_agent.config import REPO_ROOT, Settings
from support_agent.data.validate_docs import parse_document
from support_agent.db.engine import make_engine
from support_agent.db.migrate import upgrade
from support_agent.db.scratch import scratch_database
from support_agent.graph.build import build_graph
from support_agent.graph.deps import GraphDeps
from support_agent.retrieval.embed import FakeEmbedder
from support_agent.retrieval.factory import build_retriever
from support_agent.retrieval.index_build import build_index, store_for
from support_agent.retrieval.index_plan import load_corpus, plan_index
from support_agent.retrieval.index_release import MilvusAdmin, release_index, rollback_index
from support_agent.retrieval.milvus_store import MilvusStore
from support_agent.retrieval.registry import IndexRegistry
from support_agent.retrieval.rerank import FakeReranker
from support_agent.retrieval.tokenization import WhitespaceTokenizer
from test_graph_knowledge import CoverageFake, fast_model, part
from test_index_plan import document


@contextmanager
def scratch_registry(settings: Settings, path: Path) -> Iterator[IndexRegistry]:
    def opened(url: URL) -> IndexRegistry:
        engine = make_engine(url, settings.db)
        try:
            upgrade(engine)
        except Exception:
            engine.dispose()
            raise
        return IndexRegistry(engine)

    configured = os.getenv("ATLAS_TEST_PG_URL")
    if configured:
        url = make_url(configured)
        if url.port is None or url.port in settings.index.blocked_postgres_ports:
            raise ValueError("Integration registry needs an explicit dedicated Atlas port")
        settings.database_url = SecretStr(configured)
        with scratch_database(settings) as target:
            registry = opened(target)
            try:
                yield registry
            finally:
                registry.close()
    else:
        registry = opened(URL.create("sqlite", database=str(path)))
        try:
            yield registry
        finally:
            registry.close()


def isolated_settings(path: Path) -> Settings:
    settings = Settings()
    prefix = settings.index.integration_prefix + uuid4().hex + "_"
    settings.index.live_alias = prefix + "live"
    settings.index.collection_prefix = prefix + "b"
    settings.milvus.collection = settings.index.live_alias
    settings.data.processed_dir = str(path)
    return settings


class RecordingEmbedder(FakeEmbedder):
    def __init__(self, dimension: int) -> None:
        super().__init__(dimension)
        self.texts: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.texts.extend(texts)
        return super().embed(texts)


@pytest.mark.integration
def test_freshness_after_release_rollback_and_delete(tmp_path: Path) -> None:
    base = Settings()
    real_doc = REPO_ROOT / base.data.processed_dir / "docs/returns.md"
    if not real_doc.is_file():
        pytest.skip("Build the local policy documents first")
    sections, _ = parse_document(real_doc.read_text(encoding="utf-8"))
    sid, before = next(
        (sid, text)
        for sid, text in sections.items()
        if "maktek_faqs" in sid and re.search(r"within \d+ days of purchase", text)
    )
    match = re.search(r"within (\d+) days of purchase", before)
    assert match is not None
    old_window = match.group()
    after = before.replace(old_window, f"within {int(match[1]) + 15} days of purchase", 1)
    new_window = re.search(r"within \d+ days of purchase", after).group()
    other = next(key for key in sections if key != sid)
    docs = tmp_path / "docs"
    docs.mkdir()
    path = docs / "returns.md"
    settings = isolated_settings(tmp_path / "processed")
    settings.gate.threshold = 0.25  # Synthetic fixture only.
    embedder = RecordingEmbedder(settings.retrieval.embedding_dim)
    admin = MilvusAdmin(settings)

    def write(text: str, *, include_other: bool = True) -> None:
        selected = [(sid, "Generic return window", text)]
        if include_other:
            selected.append((other, "Other return policy", sections[other]))
        path.write_text(document(*selected), encoding="utf-8")

    def check(*_):
        return ReleaseDecision("release"), "fixture-release"

    with scratch_registry(settings, tmp_path / "scratch.sqlite") as registry:

        def build():
            return build_index(
                settings,
                registry,
                docs_dir=docs,
                embedder=embedder,
                tokenizer=WhitespaceTokenizer(),
            )

        live = MilvusStore(settings)
        try:
            write(before)
            initial = build()
            release_index(settings, registry, admin, initial.build_id, check)
            assert live.ready()
            saved = store_for(settings, initial.collection)
            try:
                unchanged = saved.read_vectors([other])
            finally:
                saved.close()
            write(after)
            original = registry.get_build(initial.build_id)
            plan = plan_index(
                load_corpus(docs), original, registry.build_sections(initial.build_id), settings
            )
            assert plan.changed == [sid] and plan.unchanged == [other]
            embedder.texts.clear()
            changed = build()
            assert changed.embedded_chunks == len(embedder.texts)
            assert changed.copied_chunks == len(unchanged)
            assert (
                changed.embedded_chunks
                == registry.build_sections(changed.build_id)[sid].chunk_count
            )
            release_index(settings, registry, admin, changed.build_id, check)
            assert live.read_vectors([other]) == unchanged
            new_chunk = next(
                row
                for row in live.read_chunks()
                if row.section_id == sid and new_window in row.text
            )
            retriever = build_retriever(
                "hybrid_rerank",
                settings=settings,
                store=live,
                embedder=embedder,
                reranker=FakeReranker({new_chunk.chunk_id: 12}),
            )
            question = "What is the generic return window from purchase?"
            ranked = retriever.retrieve(question, settings.retrieval.rerank_top_k)
            assert ranked[0].chunk_id == new_chunk.chunk_id
            assert all(old_window not in row.text for row in ranked)
            model = CoverageFake(
                responses=["unused"],
                payload={
                    "parts": [
                        part(
                            answer=f"You can return products {new_window}.",
                            evidence=[{"source": 1, "quote": new_window}],
                        )
                    ]
                },
            )
            with GraphDeps(
                settings, fast_model=fast_model(), main_model=model, retriever=retriever
            ) as deps:
                result = build_graph(deps).invoke(
                    {"messages": [HumanMessage(content=question)]},
                    {"configurable": {"thread_id": "freshness"}},
                )
            assert result["trace"][-3:] == ["gate", "answer", "output_guard"]
            assert new_window in result["answer"]
            assert result["citations"][0]["chunk_id"] == new_chunk.chunk_id
            rollback_index(settings, registry, admin)
            assert any(old_window in row.text for row in live.search_bm25("return purchase", 5))
            write(before, include_other=False)
            deleted = build()
            release_index(settings, registry, admin, deleted.build_id, check)
            assert not live.read_vectors([other])
            assert all(row.section_id != other for row in live.search_bm25("return", 5))
        finally:
            live.close()
            try:
                if admin.alias_target() is not None:
                    admin.store.client.drop_alias(alias=settings.index.live_alias)
                for build in registry.builds():
                    admin.drop(build.collection)
            finally:
                admin.close()


@pytest.mark.integration
def test_milvus_alias_readiness_describe_and_search(tmp_path: Path) -> None:
    settings = isolated_settings(tmp_path / "processed")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "returns.md").write_text(document(("returns.window", "Window", "Orchid returns.")))
    with scratch_registry(settings, tmp_path / "scratch.sqlite") as registry:
        admin = MilvusAdmin(settings)
        alias = MilvusStore(settings)
        try:
            assert not alias.ready()
            build = build_index(
                settings,
                registry,
                docs_dir=docs,
                embedder=FakeEmbedder(settings.retrieval.embedding_dim),
                tokenizer=WhitespaceTokenizer(),
            )
            admin.switch(build.collection, None)
            # Some Milvus releases expose aliases to HasCollection and others don't.
            # Both the direct SDK behavior and the alias-aware readiness are probed.
            has_alias = alias.has_collection(settings.index.live_alias)
            assert isinstance(has_alias, bool) and alias.ready()
            described = alias.client.describe_collection(collection_name=settings.index.live_alias)
            assert described["collection_name"] == build.collection
            assert alias.search_bm25("orchid", 1)[0].section_id == "returns.window"
        finally:
            alias.close()
            try:
                if admin.alias_target() is not None:
                    admin.store.client.drop_alias(alias=settings.index.live_alias)
                for build in registry.builds():
                    admin.drop(build.collection)
            finally:
                admin.close()
