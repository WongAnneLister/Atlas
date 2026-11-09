from __future__ import annotations

import json
from pathlib import Path

import pytest
from eval.retrieval_experiment import Experiment
from eval.retrieval_records import RetrievalRun, RunMetadata
from eval.retrieval_report import write_reports
from eval.schema import EvalItem

from support_agent.config import get_settings
from support_agent.retrieval.rerank import FakeReranker
from test_retrieval import QueryEmbedder, SearchStore


def question() -> EvalItem:
    return EvalItem(
        id="fixture",
        group="basic_policy",
        split="dev",
        question="W40?",
        gold_sections=["product.a"],
        answer_points=["Fixture answer."],
        answerable=True,
        source="fixture",
    )


def metadata() -> RunMetadata:
    return RunMetadata(
        git_sha="base-sha",
        code_hash="code-sha",
        config_hash="config-sha",
        eval_file_hash="eval-sha",
        frozen_set_hash="set-sha",
        corpus_hash="corpus-sha",
        date="2026-11-09",
        dataset_versions={"fixture": "fixed"},
        models={"embedding": "embed@revision", "reranker": "rerank@revision"},
        settings=get_settings().model_dump(mode="json"),
        reviewed=0,
        total_items=1,
        index_identities={"baseline": "fixture-index"},
    )


def test_cache_reuses_real_timings_and_invalidates_changed_provenance(tmp_path: Path) -> None:
    settings = get_settings()
    store, embedder = SearchStore(), QueryEmbedder()
    experiment = Experiment(settings, store, embedder, FakeReranker(), tmp_path, "snapshot-a")
    first = experiment.retrieve("hybrid_rerank", question())
    assert set(first.chunks[0].scores) == {"dense", "bm25", "rrf", "rerank", "rerank_logit"}
    assert len(store.calls) == 2
    second = experiment.retrieve("hybrid_rerank", question())
    assert len(store.calls) == 2
    assert second.latency_s == first.latency_s
    assert second.cache_hit
    experiment = Experiment(settings, store, embedder, FakeReranker(), tmp_path, "snapshot-b")
    experiment.retrieve("hybrid", question())
    assert len(store.calls) == 4


def test_report_header_metrics_and_csv_do_not_export_source_text(tmp_path: Path) -> None:
    experiment = Experiment(
        get_settings(), SearchStore(), QueryEmbedder(), FakeReranker(), tmp_path / "cache", "id"
    )
    record = experiment.retrieve("hybrid", question())
    run = RetrievalRun(metadata=metadata(), records=[record], requested_split="dev")
    write_reports(run, tmp_path / "reports", tmp_path / "RETRIEVAL.md")
    report = (tmp_path / "reports/retrieval.md").read_text()
    for field in [
        "base-sha",
        "config-sha",
        "code-sha",
        "eval-sha",
        "set-sha",
        "2026-11-09",
        "embed@revision",
        "rerank@revision",
        "dev",
        "fixed",
    ]:
        assert field in report
    assert "Recall@1" in report and "MRR" in report
    assert "1.0000" in report
    assert "unreviewed" in report
    csv = (tmp_path / "reports/retrieval_dev.csv").read_text()
    assert "product.a" in csv and "hybrid" in csv
    assert question().question not in csv
    assert record.chunks[0].text not in csv
    assert "Source: eval/reports/retrieval.md" in (tmp_path / "RETRIEVAL.md").read_text()


def test_failed_backend_does_not_write_success_cache(tmp_path: Path) -> None:
    class BrokenStore(SearchStore):
        def search_bm25(self, text: str, limit: int) -> list:
            raise RuntimeError("dependency failed")

    experiment = Experiment(
        get_settings(), BrokenStore(), QueryEmbedder(), FakeReranker(), tmp_path, "snapshot"
    )
    with pytest.raises(RuntimeError, match="dependency failed"):
        experiment.retrieve("hybrid", question())
    records = [json.loads(path.read_text()) for path in tmp_path.rglob("*.json")]
    assert all(record["mode"] != "hybrid" for record in records)


def test_ablations_reuse_only_the_unchanged_component(tmp_path: Path) -> None:
    settings = get_settings()
    base_store, heading_store, raw_store = SearchStore(), SearchStore(), SearchStore()
    base = Experiment(settings, base_store, QueryEmbedder(), FakeReranker(), tmp_path, "base")
    original = base.retrieve("hybrid", question())
    heading = settings.model_copy(deep=True)
    heading.chunk.prepend_heading = False
    heading_result = Experiment(
        heading,
        heading_store,
        QueryEmbedder(),
        FakeReranker(),
        tmp_path,
        "heading",
        bm25_source=base,
    ).retrieve("hybrid", question())
    raw = settings.model_copy(deep=True)
    raw.retrieval.bm25_normalise_model_numbers = False
    raw_result = Experiment(
        raw,
        raw_store,
        QueryEmbedder(),
        FakeReranker(),
        tmp_path,
        "raw",
        dense_source=base,
    ).retrieve("hybrid", question())
    assert [call[0] for call in base_store.calls] == ["dense", "bm25"]
    assert [call[0] for call in heading_store.calls] == ["dense"]
    assert [call[0] for call in raw_store.calls] == ["bm25"]
    assert heading_result.components_s["bm25"] == original.components_s["bm25"]
    assert raw_result.components_s["dense"] == original.components_s["dense"]
