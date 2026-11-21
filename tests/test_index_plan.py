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


def test_plan_compares_with_selected_build_and_not_other_versions(tmp_path) -> None:
    from support_agent.retrieval.index_models import BuildRecord, BuildSection
    from support_agent.retrieval.index_plan import index_fingerprint, load_corpus, plan_index

    path = tmp_path / "returns.md"
    path.write_text(
        document(
            ("a", "Title", "Same."),
            ("b", "Heading", "Old."),
            ("c", "Gone", "Deleted."),
            ("d", "Old heading", "Same."),
        )
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
    path.write_text(
        document(
            ("a", "Title", "Same."),
            ("b", "Heading", "New."),
            ("d", "New heading", "Same."),
            ("e", "Added", "New."),
        )
    )
    plan = plan_index(load_corpus(tmp_path), live, snapshots, settings)
    assert (plan.added, plan.changed, plan.deleted, plan.unchanged) == (
        ["e"],
        ["b", "d"],
        ["c"],
        ["a"],
    )
    assert plan.mode == "incremental"


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
    monkeypatch.setattr(index_plan, "CHUNKER_VERSION", "changed")
    assert index_plan.index_fingerprint(settings) != base


def test_chunker_golden_section() -> None:
    from support_agent.retrieval.chunking import CHUNKER_VERSION, chunk_document
    from support_agent.retrieval.tokenization import WhitespaceTokenizer

    expected = {
        "1": [
            (
                "f49364abdc6fd57dd040e75c21faf27044d973171979df8d5fc6d676dff5294f",
                "Returns > Window",
                "Returns close after thirty days.",
            )
        ]
    }
    chunks = chunk_document(
        document(("returns.window", "Window", "Returns close after thirty days.")),
        Settings().chunk,
        WhitespaceTokenizer(),
    )
    assert [(chunk.chunk_id, chunk.heading_path, chunk.text) for chunk in chunks] == expected[
        CHUNKER_VERSION
    ]
