import json
from datetime import date
from pathlib import Path

import pytest

from support_agent.config import Settings

DOC = """---
doc_id: returns
title: Returns
source_datasets: [fixture]
built_at: "2026-11-21"
---
"""


def document(*sections: tuple[str, str, str]) -> str:
    return DOC + "\n".join(
        f"## {heading}\n<!-- section: {sid} -->\n{text}\n" for sid, heading, text in sections
    )


def write_docs(folder: Path, *sections: tuple[str, str, str]) -> None:
    (folder / "returns.md").write_text(document(*sections), encoding="utf-8")
    metadata = {
        sid: {
            "doc_type": "policy",
            "topic": "returns",
            "product_category": "",
            "effective_from": "2026-01-01",
            "effective_to": None,
            "region": "global",
        }
        for sid, _, _ in sections
    }
    (folder / "section_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")


def test_plan_compares_with_selected_build_and_not_other_versions(tmp_path) -> None:
    from support_agent.retrieval.index_models import BuildRecord, BuildSection
    from support_agent.retrieval.index_plan import index_fingerprint, load_corpus, plan_index

    write_docs(
        tmp_path,
        ("a", "Title", "Same."),
        ("b", "Heading", "Old."),
        ("c", "Gone", "Deleted."),
        ("d", "Old heading", "Same."),
        ("f", "Same heading", "Same prose."),
    )
    old = load_corpus(tmp_path)
    snapshots = {
        sid: BuildSection(
            section_id=sid, section_version=1, content_hash=section.content_hash, chunk_count=1
        )
        for sid, section in old.sections.items()
    }
    settings = Settings()
    live = BuildRecord(
        build_id="aa",
        collection="fixture",
        mode="full",
        fingerprint=index_fingerprint(settings),
        embed_model="fake",
        embed_revision="fake",
        chunker_version="1",
        docs_hash=old.docs_hash,
    )
    write_docs(
        tmp_path,
        ("a", "Title", "Same."),
        ("b", "Heading", "New."),
        ("d", "New heading", "Same."),
        ("e", "Added", "New."),
        ("f", "Same heading", "Same prose."),
    )
    sidecar = tmp_path / "section_metadata.json"
    meta = json.loads(sidecar.read_text())
    meta["f"]["effective_from"] = "2026-09-01"
    sidecar.write_text(json.dumps(meta))
    plan = plan_index(load_corpus(tmp_path), live, snapshots, settings)
    assert (plan.added, plan.changed, plan.deleted, plan.unchanged) == (
        ["e"],
        ["b", "d", "f"],
        ["c"],
        ["a"],
    )
    assert plan.mode == "incremental"


def test_build_and_preview_require_metadata_for_each_section(tmp_path: Path) -> None:
    from support_agent.retrieval.chunking import load_chunks
    from support_agent.retrieval.index_plan import load_corpus
    from support_agent.retrieval.tokenization import WhitespaceTokenizer

    write_docs(tmp_path, ("a", "Window", "Return this item."))
    path = tmp_path / "section_metadata.json"
    path.write_text("{}")
    with pytest.raises(ValueError, match="Missing section metadata for a"):
        load_corpus(tmp_path)
    with pytest.raises(ValueError, match="Missing section metadata for a"):
        load_chunks(tmp_path, Settings().chunk, WhitespaceTokenizer())


def test_build_and_preview_carry_the_same_dated_metadata(tmp_path: Path) -> None:
    from support_agent.retrieval.chunking import load_chunks
    from support_agent.retrieval.index_plan import chunks_for, load_corpus
    from support_agent.retrieval.tokenization import WhitespaceTokenizer

    settings = Settings()
    tokenizer = WhitespaceTokenizer()
    write_docs(tmp_path, ("a", "Window", "Return this item."))
    preview = load_chunks(tmp_path, settings.chunk, tokenizer)
    chunks = chunks_for(load_corpus(tmp_path), ["a"], settings, tokenizer)
    assert chunks == preview
    assert chunks[0].effective_from == date(2026, 1, 1)
    assert chunks[0].effective_to is None
    assert chunks[0].topic == "returns"


def test_fingerprint_covers_the_embedding_and_chunk_schema(monkeypatch) -> None:
    from support_agent.retrieval import index_plan

    settings = Settings()
    base = index_plan.index_fingerprint(settings)
    assert base == index_plan.index_fingerprint(settings.model_copy(deep=True))
    for field, value in (
        ("embedding_model", "other"),
        ("embedding_revision", "other"),
        ("embedding_dim", 32),
        ("embedding_normalize", not settings.retrieval.embedding_normalize),
        ("embedding_window_tokens", settings.retrieval.embedding_window_tokens - 1),
    ):
        copy = settings.model_copy(deep=True)
        setattr(copy.retrieval, field, value)
        assert index_plan.index_fingerprint(copy) != base
    copy = settings.model_copy(deep=True)
    copy.chunk.prepend_heading = not copy.chunk.prepend_heading
    assert index_plan.index_fingerprint(copy) != base
    copy = settings.model_copy(deep=True)
    copy.milvus.metadata_max_bytes += 1
    assert index_plan.index_fingerprint(copy) != base
    copy = settings.model_copy(deep=True)
    copy.policy_versions.open_end_day -= 1
    assert index_plan.index_fingerprint(copy) != base
    monkeypatch.setattr(index_plan, "CHUNKER_VERSION", "changed")
    assert index_plan.index_fingerprint(settings) != base


def test_chunker_golden_section() -> None:
    from support_agent.retrieval.chunking import CHUNKER_VERSION, chunk_document
    from support_agent.retrieval.tokenization import WhitespaceTokenizer

    policy = [
        (
            "f49364abdc6fd57dd040e75c21faf27044d973171979df8d5fc6d676dff5294f",
            "Returns > Window",
            "Returns close after thirty days.",
        )
    ]
    # Version 2 changed only long product sections; policy sections keep their chunks.
    expected = {"1": policy, "2": policy}
    chunks = chunk_document(
        document(("returns.window", "Window", "Returns close after thirty days.")),
        Settings().chunk,
        WhitespaceTokenizer(),
    )
    assert [(chunk.chunk_id, chunk.heading_path, chunk.text) for chunk in chunks] == expected[
        CHUNKER_VERSION
    ]


def test_chunk_preview_reports_metadata_hash_without_replacing_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eval import ingestion

    from support_agent.data.manifest import Manifest
    from support_agent.ingest import run
    from support_agent.retrieval.index_plan import load_corpus
    from support_agent.retrieval.tokenization import WhitespaceTokenizer

    settings = Settings()
    settings.data.processed_dir = str(tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()
    write_docs(docs, ("a", "Window", "Return this item."))
    monkeypatch.setattr("support_agent.ingest.BgeTokenizer", lambda _: WhitespaceTokenizer())
    preview = run(settings, chunks_only=True)
    assert preview.corpus_hash == load_corpus(docs).docs_hash

    monkeypatch.setattr(ingestion, "get_settings", lambda: settings)
    monkeypatch.setattr(ingestion, "load_manifest", lambda _: Manifest())
    writes = []
    monkeypatch.setattr(ingestion, "write_text", lambda path, text: writes.append((path, text)))
    ingestion.main(preview=True)
    assert len(writes) == 1
    assert writes[0][0] == tmp_path / settings.index.preview_directory / "ingestion.md"
    assert preview.corpus_hash in writes[0][1]
