"""Ingest-time hard cap on chunk size (28g): an oversized chunk fails the build by name."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import URL

from support_agent.config import ChunkSettings, Settings, get_settings
from support_agent.data.build_docs import document
from support_agent.db.engine import make_engine
from support_agent.retrieval.chunking import (
    ChunkSizeError,
    check_chunk_sizes,
    chunk_document,
    chunk_size_stats,
)
from support_agent.retrieval.embed import FakeEmbedder
from support_agent.retrieval.registry import IndexRegistry
from support_agent.retrieval.tokenization import WhitespaceTokenizer
from test_index_plan import write_docs

MANUAL = " ".join(f"m{i}." for i in range(12))


def leaky(config: ChunkSettings) -> ChunkSettings:
    # A chunker rule that keeps a 12-token manual whole past an 8-token cap: the commit 06
    # defect in miniature. model_copy skips the validator, as a code bug would.
    return config.model_copy(
        update={
            "max_tokens": 4,
            "overlap_tokens": 1,
            "strategy": "token",
            "product_whole_max_tokens": 20,
            "hard_max_tokens": 8,
        }
    )


def test_check_names_every_oversized_chunk_and_passes_good_ones() -> None:
    config = leaky(get_settings().chunk)
    text = document(
        "catalog",
        ["fixture"],
        "2026-11-09",
        [
            "## Philips XY100\n<!-- section: product.XY100 -->\n\n" + MANUAL,
            "## Window\n<!-- section: returns.window -->\n\nReturns close after thirty days.",
        ],
    )
    chunks = chunk_document(text, config, WhitespaceTokenizer())
    oversized = [c for c in chunks if c.section_id == "product.XY100"]
    assert len(oversized) == 1 and oversized[0].n_tokens == 12
    with pytest.raises(ChunkSizeError) as error:
        check_chunk_sizes(chunks, config)
    message = str(error.value)
    assert f"{oversized[0].chunk_id} product.XY100 12 tokens" in message
    assert "returns.window" not in message
    check_chunk_sizes([c for c in chunks if c.section_id == "returns.window"], config)


def test_size_stats_report_max_p99_and_count_over_max_tokens() -> None:
    config = get_settings().chunk.model_copy(update={"max_tokens": 4, "overlap_tokens": 1})
    sections = [
        f"## S{i}\n<!-- section: returns.s{i} -->\n\n" + " ".join(["w"] * (i + 1)) for i in range(4)
    ]
    chunks = chunk_document(
        document("returns", ["fixture"], "2026-11-09", sections), config, WhitespaceTokenizer()
    )
    stats = chunk_size_stats(chunks, config)
    assert (stats.count, stats.max_tokens, stats.p99_tokens) == (4, 4, 4)
    assert stats.over_max_tokens == 0 and stats.hard_max_tokens == config.hard_max_tokens


def _build(tmp_path, settings: Settings):
    from support_agent.retrieval.index_build import build_index

    registry = IndexRegistry(
        make_engine(URL.create("sqlite", database=str(tmp_path / "index.sqlite")), settings.db)
    )
    created: list[str] = []

    class Store:
        def __init__(self, collection: str) -> None:
            self.collection = collection
            self.rows: list = []

        def validate(self, chunks, embeddings) -> None:
            assert len(chunks) == len(embeddings)

        def create(self) -> None:
            created.append(self.collection)

        def upsert(self, chunks, embeddings) -> None:
            self.rows = list(chunks)

        def count(self) -> int:
            return len(self.rows)

        def read_chunks(self):
            return self.rows

        def read_vectors(self, section_ids):
            return []

        def close(self) -> None:
            pass

        def drop(self) -> None:
            pass

    try:
        result = build_index(
            settings,
            registry,
            docs_dir=tmp_path,
            tokenizer=WhitespaceTokenizer(),
            embedder=FakeEmbedder(4),
            make_store=Store,
        )
        return result, created, [build.status for build in registry.builds()]
    except ChunkSizeError as error:
        return error, created, [build.status for build in registry.builds()]
    finally:
        registry.close()


def test_build_fails_on_an_oversized_chunk_and_names_it(tmp_path) -> None:
    settings = Settings()
    settings.data.processed_dir = str(tmp_path)
    settings.retrieval.embedding_dim = 4
    settings.chunk = leaky(settings.chunk)
    write_docs(tmp_path, ("product.XY100", "Philips XY100", MANUAL), ("a", "Window", "Keep."))
    error, created, statuses = _build(tmp_path, settings)
    assert isinstance(error, ChunkSizeError)
    assert "product.XY100 12 tokens" in str(error) and "over the 8-token" in str(error)
    assert created == [] and statuses == ["failed"]


def test_build_records_the_chunk_size_distribution(tmp_path) -> None:
    settings = Settings()
    settings.data.processed_dir = str(tmp_path)
    settings.retrieval.embedding_dim = 4
    write_docs(tmp_path, ("a", "Window", "Returns close after thirty days."))
    result, created, statuses = _build(tmp_path, settings)
    assert statuses == ["built"] and len(created) == 1
    assert result.chunk_sizes.count == 1 and result.chunk_sizes.max_tokens == 5
    assert result.chunk_sizes.over_max_tokens == 0


def test_cap_settings_are_checked() -> None:
    chunk = get_settings().chunk.model_dump()
    with pytest.raises(ValidationError, match="hard_max_tokens"):
        ChunkSettings.model_validate({**chunk, "hard_max_tokens": chunk["max_tokens"] - 1})
    with pytest.raises(ValidationError, match="product_whole_max_tokens"):
        ChunkSettings.model_validate(
            {**chunk, "product_whole_max_tokens": chunk["hard_max_tokens"] + 1}
        )
    settings = get_settings()
    verify = settings.context.profiles["verify"].total_tokens
    assert settings.chunk.hard_max_tokens <= verify // 2
    with pytest.raises(ValidationError, match="half the verify budget"):
        Settings.model_validate(
            {
                **settings.model_dump(),
                "chunk": {**chunk, "hard_max_tokens": verify, "product_whole_max_tokens": 512},
            }
        )


def test_release_report_line_shows_the_build_chunk_sizes(tmp_path) -> None:
    from eval.index_release_runner import chunk_size_note

    from support_agent.retrieval.index_build import save_build_snapshot

    settings = Settings()
    settings.data.processed_dir = str(tmp_path)
    text = document(
        "returns",
        ["fixture"],
        "2026-11-09",
        ["## Window\n<!-- section: returns.window -->\n\nReturns close after thirty days."],
    )
    chunks = chunk_document(text, settings.chunk, WhitespaceTokenizer())
    save_build_snapshot(settings, "abc123", chunks)
    note = chunk_size_note(settings, "Candidate", "abc123")
    assert note.startswith("Candidate build abc123 chunk sizes: 1 chunks, max 5, p99 5, 0 over")
    assert "snapshot unavailable" in chunk_size_note(settings, "Live", "def456")


def test_the_cap_does_not_change_the_index_fingerprint() -> None:
    # Raising or lowering the guard must not force a rebuild of identical chunks.
    from support_agent.retrieval.index_plan import index_fingerprint

    settings = get_settings().model_copy(deep=True)
    base = index_fingerprint(settings)
    settings.chunk.hard_max_tokens -= 1
    assert index_fingerprint(settings) == base
    settings.chunk.product_whole_max_tokens -= 1
    assert index_fingerprint(settings) != base


def test_chunk_size_report_fails_a_build_over_the_cap(tmp_path, monkeypatch) -> None:
    from eval import chunk_sizes

    from support_agent.retrieval.index_build import save_build_snapshot

    settings = Settings()
    settings.data.processed_dir = str(tmp_path)
    settings.chunk = leaky(settings.chunk)
    monkeypatch.setattr(chunk_sizes, "get_settings", lambda: settings)
    text = document(
        "catalog",
        ["fixture"],
        "2026-11-09",
        ["## Philips XY100\n<!-- section: product.XY100 -->\n\n" + MANUAL],
    )
    save_build_snapshot(
        settings, "bad1", chunk_document(text, settings.chunk, WhitespaceTokenizer())
    )
    output, ok = chunk_sizes.report(["bad1"])
    assert not ok and "| fail |" in output and "product.XY100 12 tokens" in output
