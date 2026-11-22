"""Offline tests for the e2e evaluator speed-ups (no model, no Milvus, no network)."""

from __future__ import annotations

import argparse
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eval import compare, e2e_eval, e2e_speed, gate
from eval.e2e_speed import (
    SpeedOptions,
    add_speed_arguments,
    comparable_rules,
    merge_rerank_scores,
    rerank_scores,
    run_config_hash,
    run_items,
    speed_options,
)
from eval.multipart_eval import collect
from eval.rerank_cache import (
    CachedReranker,
    ScoreCache,
    cache_path,
    score_profile,
    shared_cache_path,
)
from eval.run_record import read_run
from eval.schema import EvalItem, MultipartItem, MultipartPart

from support_agent.config import Settings
from support_agent.data.doc_models import digest, json_text
from support_agent.graph import deps as deps_module
from support_agent.graph.deps import GraphDeps
from support_agent.observability.cost import UsageLedger
from support_agent.retrieval.rerank import BgeReranker, RerankingRetriever
from test_rerank_cache import Backend
from test_retrieval import item

CHUNKS = [item(key) for key in "abcd"]


def _settings(tmp_path: Path) -> Settings:
    settings = Settings().model_copy(deep=True)
    settings.index.release.rerank_cache.path = str(tmp_path / "scores.sqlite")
    return settings


def _graph_rerank(settings: Settings, backend: Backend, monkeypatch):
    """Rerank CHUNKS through GraphDeps' guarded reranker, as a graph node does."""
    monkeypatch.setattr(deps_module, "BgeM3Embedder", lambda config: object())
    scorer = lambda: BgeReranker(settings.retrieval, backend=backend)  # noqa: E731
    with (
        rerank_scores(settings, True, scorer=scorer) as scores,
        GraphDeps(settings, reranker_factory=scores.factory()) as deps,
    ):
        retriever = deps.knowledge_retriever()
        assert isinstance(retriever, RerankingRetriever)
        # The guard runs the reranker on its own worker thread, not the caller's.
        ranked = retriever.reranker.rerank("query", CHUNKS)
        return ranked, scores.summary()


def test_cached_and_uncached_graph_reranks_are_identical(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    expected = BgeReranker(settings.retrieval, backend=Backend()).rerank("query", CHUNKS)

    # Off by default: GraphDeps keeps its own BgeReranker, whose rerank built ``expected``.
    with rerank_scores(settings, settings.eval.e2e_speed.rerank_cache) as off:
        assert off.factory() is None
        assert off.summary() is None
    assert not (tmp_path / "scores.sqlite").exists()

    cold_backend = Backend()
    cold, cold_summary = _graph_rerank(settings, cold_backend, monkeypatch)
    assert cold == expected
    assert cold_backend.calls == [[("query", chunk.text) for chunk in CHUNKS]]
    assert cold_summary is not None
    assert (cold_summary["from_cache"], cold_summary["scored"]) == (0, 4)

    warm_backend = Backend()
    warm, warm_summary = _graph_rerank(settings, warm_backend, monkeypatch)
    assert warm == expected
    assert warm_backend.calls == []
    assert warm_summary is not None
    assert (warm_summary["from_cache"], warm_summary["scored"]) == (4, 0)
    assert warm_summary["profile"] == score_profile(settings).key


def test_e2e_reads_logits_the_release_path_wrote_under_the_same_key(
    tmp_path: Path, monkeypatch
) -> None:
    settings = _settings(tmp_path)
    assert shared_cache_path(settings) == cache_path(settings)
    # Exactly what index_release.collect_run builds.
    release_cache = ScoreCache(shared_cache_path(settings), score_profile(settings))
    release = CachedReranker(BgeReranker(settings.retrieval, backend=Backend()), release_cache)
    expected = release.rerank("query", CHUNKS)
    release_cache.close()

    # Release evidence may score every pair; e2e still reads the shared file.
    settings.index.release.rerank_cache.enabled = False
    reused = Backend()
    result, summary = _graph_rerank(settings, reused, monkeypatch)
    assert result == expected
    assert reused.calls == []
    assert summary is not None and summary["from_cache"] == 4

    other_device = settings.model_copy(deep=True)
    other_device.retrieval.reranker_device = "mps"
    missed = Backend()
    _, summary = _graph_rerank(other_device, missed, monkeypatch)
    assert summary is not None and (summary["from_cache"], summary["scored"]) == (0, 4)
    assert len(missed.calls) == 1


def test_config_hash_leaves_out_the_speed_switches() -> None:
    settings = Settings().model_copy(deep=True)
    base = run_config_hash(settings)
    settings.eval.e2e_speed.rerank_cache = True
    settings.eval.e2e_speed.max_workers = 3
    assert run_config_hash(settings) == base
    dumped = settings.model_dump(mode="json")
    del dumped["eval"]["e2e_speed"]
    assert base == digest(json_text(dumped))
    settings.gate.untuned_threshold = 0.99
    assert run_config_hash(settings) != base


def _options(argv: list[str], settings: Settings) -> SpeedOptions:
    parser = argparse.ArgumentParser()
    add_speed_arguments(parser)
    return speed_options(parser.parse_args(argv), settings, parser)


def test_speed_options_default_off_and_bounded() -> None:
    settings = Settings().model_copy(deep=True)
    assert settings.eval.e2e_speed.rerank_cache is False
    assert _options([], settings) == SpeedOptions(workers=1, rerank_cache=False)
    assert _options(["--rerank-cache", "--workers", "2"], settings) == SpeedOptions(2, True)
    settings.eval.e2e_speed.rerank_cache = True
    assert _options([], settings).rerank_cache is True
    assert _options(["--no-rerank-cache"], settings).rerank_cache is False
    for workers in ("0", str(settings.eval.e2e_speed.max_workers + 1)):
        with pytest.raises(SystemExit):
            _options(["--workers", workers], settings)
    settings.eval.e2e_speed.rerank_cache = False
    settings.chaos.enabled = True
    assert _options([], settings) == SpeedOptions()
    with pytest.raises(SystemExit):
        _options(["--workers", "2"], settings)


def test_resumed_counts_add_up_and_refuse_a_new_profile() -> None:
    saved = {"cache": "c", "profile": "p", "from_cache": 3, "scored": 2}
    now = {"cache": "c", "profile": "p", "from_cache": 5, "scored": 1}
    assert merge_rerank_scores(saved, now) == {**now, "from_cache": 8, "scored": 3}
    assert merge_rerank_scores(None, now) == now
    assert merge_rerank_scores(saved, None) == saved
    assert merge_rerank_scores(None, None) is None
    with pytest.raises(ValueError, match="profile changed"):
        merge_rerank_scores(saved, {**now, "profile": "q"})


def _reverse_finisher(count: int) -> tuple[Any, list[int]]:
    """Work where item i returns only after item i+1 has returned."""
    finished = [threading.Event() for _ in range(count)]
    order: list[int] = []

    def work(index: int) -> str:
        if index + 1 < count:
            assert finished[index + 1].wait(5)
        order.append(index)
        finished[index].set()
        return f"result-{index}"

    return work, order


def test_run_items_results_do_not_depend_on_completion_order() -> None:
    items = list(range(5))
    serial: dict[int, str] = {}
    run_items(items, lambda i: f"result-{i}", workers=1, done=serial.__setitem__)

    work, order = _reverse_finisher(len(items))
    seen: list[int] = []
    parallel: dict[int, str] = {}

    def done(index: int, result: str) -> None:
        seen.append(index)
        parallel[index] = result

    run_items(items, work, workers=len(items), done=done)
    assert order == [4, 3, 2, 1, 0]
    assert sorted(seen) == items
    assert [parallel[i] for i in items] == [serial[i] for i in items]


def test_run_items_stops_starting_items_after_a_failure_and_keeps_running_ones() -> None:
    started: list[int] = []
    failed = threading.Event()

    def work(index: int) -> int:
        started.append(index)
        if index == 1:
            failed.set()
            raise RuntimeError("item one broke")
        if index == 0:
            assert failed.wait(5)
        time.sleep(0.2)
        return index

    delivered: list[int] = []
    with pytest.raises(RuntimeError, match="item one broke"):
        run_items(list(range(8)), work, workers=2, done=lambda i, r: delivered.append(r))
    assert 0 in delivered
    assert len(started) <= 3
    assert set(delivered) <= set(started) - {1}


def test_run_items_stops_when_saving_fails() -> None:
    started: list[int] = []

    def work(index: int) -> int:
        started.append(index)
        time.sleep(0.05)
        return index

    def done(index: int, result: int) -> None:
        raise ValueError("Index build changed")

    with pytest.raises(ValueError, match="Index build changed"):
        run_items(list(range(20)), work, workers=2, done=done)
    assert len(started) < 20


def _multipart(index: int) -> MultipartItem:
    return MultipartItem(
        id=f"mp-dev-{index}",
        split="dev",
        group="answerable_pair",
        question=f"Question {index} part one, and part two?",
        source="fixture",
        parts=[
            MultipartPart(
                text=f"Part {index} {suffix}?",
                gold_sections=["returns"],
                answer_points=["30 days"],
                answerable=True,
                source_item_id=f"dev-{index}-{suffix}",
            )
            for suffix in ("one", "two")
        ],
    )


def test_multipart_collect_with_workers_matches_serial_in_input_order() -> None:
    items = [_multipart(index) for index in range(4)]
    finished = {item.question: threading.Event() for item in items}
    questions = [item.question for item in items]

    class Graph:
        def __init__(self, concurrent: bool) -> None:
            self.concurrent = concurrent

        def invoke(self, state, config):
            question = state["messages"][0].content
            position = questions.index(question)
            if self.concurrent and position + 1 < len(questions):
                assert finished[questions[position + 1]].wait(5)
            finished[question].set()
            return {"trace": ["answer"], "answer": f"Answer to {question} [1]"}

    settings = Settings()
    latency = {"latency_full_answer_s", "latency_first_token_s"}
    serial = collect(Graph(False), items, settings, None)
    for event in finished.values():
        event.clear()
    parallel = collect(Graph(True), items, settings, None, workers=len(items))
    assert [record.item.id for record in parallel] == [item.id for item in items]
    assert [r.model_dump(exclude=latency) for r in parallel] == [
        r.model_dump(exclude=latency) for r in serial
    ]


def _eval_item(index: int) -> EvalItem:
    answerable = index % 2 == 0
    return EvalItem(
        id=f"basic_policy-{index:02d}" if answerable else f"no_answer-{index:02d}",
        group="basic_policy" if answerable else "no_answer",
        split="test",
        question=f"Local question {index}",
        gold_sections=["product.a"] if answerable else [],
        answer_points=["answer"] if answerable else [],
        answerable=answerable,
        source="fixture",
    )


def _collect_e2e(
    tmp_path: Path, monkeypatch, name: str, extra: list[str], *, reverse: bool = False
) -> tuple[Path, Path, Backend]:
    """Collect four fake items; with ``reverse`` each item waits for the next to finish."""
    items = [_eval_item(index) for index in range(4)]
    eval_file = tmp_path / "items.jsonl"
    eval_file.write_text("".join(f"{row.model_dump_json()}\n" for row in items))
    (tmp_path / "manifest.json").write_text('{"corpus_hash": "corpus-hash"}')
    settings = _settings(tmp_path)
    settings.evaluation.sets_dir = str(tmp_path)
    monkeypatch.setattr(e2e_eval, "get_settings", lambda: settings)
    monkeypatch.setattr(e2e_eval, "is_dirty", lambda: False)
    monkeypatch.setattr(e2e_eval, "_git_sha", lambda: "clean-sha")
    monkeypatch.setattr(e2e_eval, "configured_build_id", lambda settings: None)
    backend = Backend()
    monkeypatch.setattr(
        e2e_speed, "BgeReranker", lambda config: BgeReranker(config, backend=backend)
    )
    finished = {row.id: threading.Event() for row in items}
    ids = [row.id for row in items]

    class FakeDeps:
        def __init__(self, settings: Settings, **kwargs: Any) -> None:
            factory = kwargs.get("reranker_factory")
            self.reranker = (
                factory() if factory else BgeReranker(settings.retrieval, backend=backend)
            )

        def __enter__(self) -> FakeDeps:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fake_item(graph, row, customer_id, thread_id, trace):
        position = ids.index(row.id)
        if reverse and position + 1 < len(ids):
            assert finished[ids[position + 1]].wait(5)
        ranked = graph.reranker.rerank(row.question, CHUNKS)
        finished[row.id].set()
        usage = UsageLedger()
        if not row.answerable:
            return {"handoff": SimpleNamespace(reason="low_evidence")}, 1.0, usage
        return (
            {
                "trace": ["answer"],
                "answer": "Answer [1]",
                "retrieval": ranked,
                "citations": [{"n": 1}],
            },
            1.0 + position,
            usage,
        )

    monkeypatch.setattr(e2e_eval, "GraphDeps", FakeDeps)
    monkeypatch.setattr(e2e_eval, "build_graph", lambda deps: deps)
    monkeypatch.setattr(e2e_eval, "_run_item", fake_item)
    pointer = tmp_path / f"{name}.txt"
    output = tmp_path / f"{name}.jsonl"
    report = tmp_path / f"{name}.md"
    argv = [
        "--allow-untuned",
        "--eval-file",
        str(eval_file),
        "--output",
        str(output),
        "--report",
        str(report),
        "--run-root",
        str(tmp_path / "runs"),
        "--run-pointer",
        str(pointer),
        *extra,
    ]
    assert e2e_eval.main(argv) == 0
    lines = output.read_text().splitlines()
    assert [json.loads(line)["item"]["id"] for line in lines[1:]] == ids
    return Path(pointer.read_text().strip()), report, backend


def test_e2e_run_records_workers_cache_counts_and_non_comparable_latency(
    tmp_path: Path, monkeypatch
) -> None:
    serial_dir, serial_report, serial_backend = _collect_e2e(tmp_path, monkeypatch, "serial", [])
    serial = read_run(serial_dir)
    assert serial.manifest.source["workers"] == 1
    assert serial.manifest.source["latency_comparable"] is True
    assert serial.manifest.source["rerank_scores"] is None
    assert len(serial_backend.calls) == 4
    assert "- Rerank score cache: off" in serial_report.read_text()
    assert "not comparable" not in serial_report.read_text()

    fast_dir, fast_report, fast_backend = _collect_e2e(
        tmp_path, monkeypatch, "fast", ["--workers", "4", "--rerank-cache"], reverse=True
    )
    fast = read_run(fast_dir)
    source = fast.manifest.source
    assert (source["workers"], source["latency_comparable"]) == (4, False)
    assert (source["rerank_scores"]["from_cache"], source["rerank_scores"]["scored"]) == (0, 16)
    assert fast.manifest.config_hash == serial.manifest.config_hash
    assert [row.id for row in fast.items] == [row.id for row in serial.items]
    assert [row.payload["retrieved_section_ids"] for row in fast.items] == [
        row.payload["retrieved_section_ids"] for row in serial.items
    ]
    assert len(fast_backend.calls) == 4
    text = fast_report.read_text()
    assert "- Item workers: 4" in text
    assert "Latency is not comparable with serial runs" in text
    assert "s (not comparable: items ran concurrently) |" in text
    assert "0/16 logits read from the cache, 16 scored" in text

    warm_dir, _, warm_backend = _collect_e2e(tmp_path, monkeypatch, "warm", ["--rerank-cache"])
    warm = read_run(warm_dir).manifest.source
    assert (warm["workers"], warm["latency_comparable"]) == (1, True)
    assert (warm["rerank_scores"]["from_cache"], warm["rerank_scores"]["scored"]) == (16, 0)
    assert warm_backend.calls == []

    output = tmp_path / "compare.md"
    assert compare.main([str(serial_dir), str(fast_dir), "--output", str(output)]) == 0
    comparison = output.read_text()
    assert "Latency not compared: a run collected items concurrently (workers 4)." in comparison
    assert "| latency_p95 |" not in comparison
    assert "| pass_rate |" in comparison


def test_gate_drops_latency_for_concurrent_runs_and_refuses_them_as_baselines(
    tmp_path: Path, monkeypatch
) -> None:
    serial_dir, _, _ = _collect_e2e(tmp_path, monkeypatch, "serial", [])
    fast_dir, _, _ = _collect_e2e(tmp_path, monkeypatch, "fast", ["--workers", "2"])
    serial, fast = read_run(serial_dir), read_run(fast_dir)
    rules = {"latency_p95": "rule", "first_token_p50": "rule", "false_accept": "rule"}
    assert comparable_rules(rules, serial, serial) == (rules, None)
    kept, note = comparable_rules(rules, serial, fast)
    assert kept == {"false_accept": "rule"}
    assert note is not None and "workers 2" in note

    monkeypatch.setattr(
        gate, "git", lambda *args: "main" if args[0] == "branch" else fast.manifest.git_sha
    )
    monkeypatch.setattr(gate, "is_dirty", lambda: False)
    with pytest.raises(ValueError, match="must be serial"):
        gate.promote(fast, "fast", tmp_path / "baseline.json")
