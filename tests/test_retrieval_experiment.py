from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from eval.legacy_core import render_retrieval, save_retrieval
from eval.retrieval_experiment import Experiment
from eval.retrieval_records import RetrievalRun, RunMetadata
from eval.schema import EvalItem

from support_agent.config import get_settings
from support_agent.retrieval.filters import RetrievalFilters
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


def test_filter_ablation_changes_both_candidate_searches_and_the_cache_key(tmp_path: Path) -> None:
    calls = []

    class FilterStore(SearchStore):
        def supports_filters(self):
            return True

        def search_dense(self, vector, limit, filters=None):
            calls.append(("dense", filters))
            return super().search_dense(vector, limit)

        def search_bm25(self, text, limit, filters=None):
            calls.append(("bm25", filters))
            return super().search_bm25(text, limit)

    experiment = Experiment(
        get_settings(), FilterStore(), QueryEmbedder(), FakeReranker(), tmp_path, "snapshot"
    )
    by_date = RetrievalFilters(as_of=date(2026, 9, 1))
    both = by_date.model_copy(update={"product_category": "monitors"})
    for filters in (None, by_date, both, by_date):
        record = experiment.retrieve("hybrid_rerank", question(), filters=filters)
        assert record.filters_applied == (filters is not None)
    assert calls == [
        (source, filters) for filters in (None, by_date, both) for source in ("dense", "bm25")
    ]
    assert record.cache_hit


def test_legacy_filter_ablation_records_that_filters_were_unsupported(tmp_path: Path) -> None:
    store = SearchStore()
    experiment = Experiment(
        get_settings(), store, QueryEmbedder(), FakeReranker(), tmp_path, "snapshot"
    )
    record = experiment.retrieve(
        "hybrid_rerank", question(), filters=RetrievalFilters(as_of=date(2026, 9, 1))
    )
    assert not record.filters_applied
    assert [call[0] for call in store.calls] == ["dense", "bm25"]


def test_report_header_metrics_and_csv_do_not_export_source_text(tmp_path: Path) -> None:
    experiment = Experiment(
        get_settings(), SearchStore(), QueryEmbedder(), FakeReranker(), tmp_path / "cache", "id"
    )
    record = experiment.retrieve("hybrid", question())
    filter_mode = "hybrid_rerank_filters_date"
    filters = RetrievalFilters(as_of=date(2026, 9, 1))
    filtered = experiment.retrieve("hybrid_rerank", question(), filters=filters).model_copy(
        update={"mode": filter_mode}
    )
    run = RetrievalRun(metadata=metadata(), records=[record, filtered], requested_split="dev")
    run_path = save_retrieval(run, [], root=tmp_path / "runs")
    render_retrieval(run_path, tmp_path / "reports", tmp_path / "RETRIEVAL.md")
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
    assert f"| dev | {filter_mode} | 0/1 |" in report
    csv = (tmp_path / "reports/retrieval_dev.csv").read_text()
    assert "product.a" in csv and "hybrid" in csv
    assert question().question not in csv
    assert record.chunks[0].text not in csv
    assert "filters_applied" in csv and "2026-09-01" in csv
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
