from __future__ import annotations

from pathlib import Path

import pytest
from eval import ingestion

from support_agent.config import get_settings
from support_agent.data.doc_models import digest
from support_agent.ingest import IngestRun
from test_milvus_store import chunk


def test_ingestion_report_keeps_handwritten_retrieval_guide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    output = tmp_path / settings.data.processed_dir
    output.mkdir(parents=True)
    text = chunk().model_dump_json() + "\n"
    (output / "chunks.jsonl").write_text(text)
    run = IngestRun(
        started_at="fixture",
        config_hash="fixture",
        chunk_hash=digest(text),
        tokenizer="fixture",
        embedding_model="fixture",
        embedding_revision="fixture",
        policy_max_tokens=settings.chunk.max_tokens,
        policy_overlap_tokens=settings.chunk.overlap_tokens,
        prepend_heading=True,
        encoder_window_tokens=settings.retrieval.embedding_window_tokens,
        chunk_count=1,
    )
    (output / "ingest_run.json").write_text(run.model_dump_json())
    docs = tmp_path / "docs"
    docs.mkdir()
    guide = "# Retrieval\n\n## Hybrid + RRF\n\nKeep this guide.\n\n"
    (docs / "RETRIEVAL.md").write_text(guide + "## Measured ingestion\n\nOld report.\n")
    monkeypatch.setattr(ingestion, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(ingestion.subprocess, "check_output", lambda *args, **kwargs: "fixture")
    monkeypatch.setattr(
        ingestion, "load_manifest", lambda *args: type("Manifest", (), {"sources": {}})()
    )
    ingestion.main()
    result = (docs / "RETRIEVAL.md").read_text()
    assert result.startswith(guide + "## Measured ingestion\n\n")
    assert "Old report." not in result
    assert "# Chunking and ingestion report" in result
    ingestion.main()
    assert (docs / "RETRIEVAL.md").read_text() == result
