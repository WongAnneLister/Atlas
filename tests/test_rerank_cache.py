"""Offline tests for the release-evidence rerank score cache (no model, no Milvus)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from eval.rerank_cache import CachedReranker, ScoreCache, ScoreProfile, score_profile, text_sha256

from support_agent.config import Settings
from support_agent.retrieval.rerank import BgeReranker
from test_retrieval import item


def _logit(query: str, text: str) -> float:
    digest = hashlib.sha256(f"{query}\x00{text}".encode()).digest()
    return int.from_bytes(digest[:4], "big") / 2**28 - 8


class Backend:
    """Deterministic stand-in for FlagReranker.compute_score that records each call."""

    def __init__(self) -> None:
        self.calls: list[list[tuple[str, str]]] = []

    def compute_score(self, pairs: list[tuple[str, str]], **kwargs: object) -> list[float]:
        self.calls.append(list(pairs))
        return [_logit(query, text) for query, text in pairs]


def _profile(**changes: object) -> ScoreProfile:
    base = score_profile(Settings(), package_version=lambda name: "1.0")
    return base.model_copy(update=changes)


def test_profile_reads_every_key_field_from_config_and_installed_packages() -> None:
    settings = Settings()
    settings.retrieval.reranker_device = "mps"
    profile = score_profile(settings, package_version=lambda name: f"{name}-v")
    retrieval = settings.retrieval
    assert profile.model == retrieval.reranker_model
    assert profile.revision == retrieval.reranker_revision
    assert profile.device == "mps"
    assert profile.use_fp16 == retrieval.reranker_use_fp16
    assert profile.max_tokens == retrieval.reranker_max_tokens
    assert profile.batch_size == retrieval.reranker_batch_size
    assert profile.packages == {
        name: f"{name}-v" for name in settings.index.release.rerank_cache.key_packages
    }


@pytest.mark.parametrize(
    "change",
    [
        {"model": "BAAI/other-reranker"},
        {"revision": "0" * 40},
        {"device": "mps"},
        {"use_fp16": True},
        {"max_tokens": 256},
        {"batch_size": 8},
        {"packages": {"FlagEmbedding": "1.0", "torch": "2.0", "transformers": "1.0"}},
    ],
)
def test_any_model_side_change_is_a_miss(tmp_path: Path, change: dict[str, object]) -> None:
    path = tmp_path / "scores.sqlite"
    passage = text_sha256("Returns are accepted within 30 days.")
    base = ScoreCache(path, _profile())
    base.put("How long do I have?", {passage: 1.5})
    assert base.get("How long do I have?", [passage]) == {passage: 1.5}
    base.close()
    changed = ScoreCache(path, _profile(**change))
    assert changed.profile.key != _profile().key
    assert changed.get("How long do I have?", [passage]) == {}
    changed.close()


def test_passage_or_query_text_change_is_a_miss(tmp_path: Path) -> None:
    cache = ScoreCache(tmp_path / "scores.sqlite", _profile())
    old = text_sha256("Returns are accepted within 30 days.")
    cache.put("How long do I have?", {old: 1.5})
    new = text_sha256("Returns are accepted within 45 days.")
    assert cache.get("How long do I have?", [new]) == {}
    assert cache.get("How long do I have?", [old]) == {old: 1.5}
    assert cache.get("How long do I have ?", [old]) == {}
    cache.close()


def test_logits_survive_a_reopen_exactly(tmp_path: Path) -> None:
    path = tmp_path / "scores.sqlite"
    value = _logit("q", "text")
    cache = ScoreCache(path, _profile())
    cache.put("q", {text_sha256("text"): value})
    cache.close()
    reopened = ScoreCache(path, _profile())
    assert reopened.get("q", [text_sha256("text")])[text_sha256("text")] == value
    reopened.close()


def test_cold_cache_scores_the_same_pairs_as_no_cache_and_warm_cache_scores_only_changes(
    tmp_path: Path,
) -> None:
    config = Settings().retrieval
    chunks = [item(key) for key in "abcd"]
    uncached_backend = Backend()
    uncached = CachedReranker(BgeReranker(config, backend=uncached_backend), None)
    expected = uncached.rerank("query", chunks)
    assert expected == BgeReranker(config, backend=Backend()).rerank("query", chunks)

    cold_backend = Backend()
    cache = ScoreCache(tmp_path / "scores.sqlite", _profile())
    cold = CachedReranker(BgeReranker(config, backend=cold_backend), cache)
    assert cold.rerank("query", chunks) == expected
    assert cold_backend.calls == uncached_backend.calls
    assert (cold.from_cache, cold.scored) == (0, 4)

    changed = [chunk.model_copy() for chunk in chunks]
    changed[2] = changed[2].model_copy(update={"text": "Model c instructions, revised."})
    warm_backend = Backend()
    warm = CachedReranker(BgeReranker(config, backend=warm_backend), cache)
    result = warm.rerank("query", changed)
    assert warm_backend.calls == [[("query", "Model c instructions, revised.")]]
    assert (warm.from_cache, warm.scored) == (3, 1)
    assert result == CachedReranker(BgeReranker(config, backend=Backend()), None).rerank(
        "query", changed
    )
    cache.close()


def test_non_finite_logits_fail_closed_and_are_not_stored(tmp_path: Path) -> None:
    class Broken:
        def logits(self, query: str, texts: list[str]) -> list[float]:
            return [float("nan")] * len(texts)

    cache = ScoreCache(tmp_path / "scores.sqlite", _profile())
    with pytest.raises(ValueError):
        CachedReranker(Broken(), cache).rerank("q", [item("a")])
    assert cache.get("q", [text_sha256(item("a").text)]) == {}
    cache.close()


def test_cached_and_uncached_release_runs_give_identical_rows(tmp_path: Path, monkeypatch) -> None:
    from eval.index_release import ReleaseSet, collect_run
    from eval.run_record import read_run
    from eval.schema import EvalItem

    from support_agent.retrieval.embed import FakeEmbedder
    from support_agent.retrieval.factory import build_retriever
    from support_agent.retrieval.milvus_store import SearchHit

    settings = Settings()
    chunks = [item(key) for key in ("w40", "w50", "returns", "warranty", "shipping")]

    class Store:
        def __init__(self, revised: bool) -> None:
            self.hits = [
                SearchHit(
                    **chunk.model_dump(exclude={"scores", "ranks"}),
                    score=1 - i / 10,
                )
                for i, chunk in enumerate(chunks)
            ]
            if revised:  # the one-section change of an incremental build
                self.hits[2] = self.hits[2].model_copy(update={"text": "Returns within 45 days."})

        def search_dense(self, vector: list[float], limit: int) -> list[SearchHit]:
            return self.hits[:limit]

        def search_bm25(self, text: str, limit: int) -> list[SearchHit]:
            return list(reversed(self.hits))[:limit]

    def question(ident: str, text: str, gold: list[str]) -> EvalItem:
        return EvalItem(
            id=ident,
            group="basic_policy" if gold else "no_answer",
            split="dev",
            question=text,
            gold_sections=gold,
            answer_points=["Point"] if gold else [],
            answerable=bool(gold),
            source="fixture",
        )

    selected = ReleaseSet(
        [
            question("a", "How long is the return window?", [chunks[2].section_id]),
            question("b", "Does W40 have a warranty?", [chunks[3].section_id]),
            question("c", "Do you sell gift wrapping?", []),
        ],
        {},
        "dev",
    )
    monkeypatch.setattr("eval.index_release.is_dirty", lambda: False)
    cache = ScoreCache(tmp_path / "scores.sqlite", score_profile(settings))
    backends: list[Backend] = []

    def run(revised: bool, use_cache: bool) -> tuple[Path, CachedReranker]:
        backends.append(Backend())
        reranker = CachedReranker(
            BgeReranker(settings.retrieval, backend=backends[-1]), cache if use_cache else None
        )
        retriever = build_retriever(
            "hybrid_rerank",
            settings=settings,
            store=Store(revised),
            embedder=FakeEmbedder(4),
            reranker=reranker,
        )
        path = collect_run(
            settings,
            "fixture",
            release_set=selected,
            retriever=retriever,
            reranker=reranker,
            run_root=tmp_path / "runs",
        )
        return path, reranker

    live_path, _ = run(revised=False, use_cache=True)  # live build fills the cache
    warm_path, warm = run(revised=True, use_cache=True)
    plain_path, plain = run(revised=True, use_cache=False)
    cache.close()

    warm_run, plain_run = read_run(warm_path), read_run(plain_path)
    assert [row.model_dump() for row in warm_run.items] == [
        row.model_dump() for row in plain_run.items
    ]
    assert warm_run.metrics == plain_run.metrics
    assert all("gate_score" in row.payload for row in warm_run.items)
    pairs = len(selected.items) * len(chunks)
    assert (warm.from_cache, warm.scored) == (pairs - len(selected.items), len(selected.items))
    assert (plain.from_cache, plain.scored) == (0, pairs)
    assert sum(map(len, backends[1].calls)) == len(selected.items)
    summary = warm_run.manifest.source["rerank_scores"]
    assert (summary["from_cache"], summary["scored"]) == (warm.from_cache, warm.scored)
    assert summary["profile"] == score_profile(settings).key
    assert plain_run.manifest.source["rerank_scores"]["cache"] is None

    from eval import rerank_cache_report

    record = {
        "device": "cpu",
        "cache_file": "scores.sqlite",
        "live_collection": "live",
        "candidate_collection": "candidate",
        "runs": {
            "live_cold": live_path.name,
            "candidate_uncached": plain_path.name,
            "candidate_warm": warm_path.name,
        },
    }
    measurement = tmp_path / "runs" / "rerank-cache-fixture"
    measurement.mkdir()
    (measurement / "measurement.json").write_text(json.dumps(record))
    monkeypatch.setattr(rerank_cache_report, "RUNS", tmp_path / "runs")
    settings.index.release.rerank_cache.path = str(tmp_path / "scores.sqlite")
    assert rerank_cache_report.latest() == measurement
    report = rerank_cache_report.render(measurement, settings)
    assert "- Rows identical (metrics, top-5 chunk ids, gate score, errors): 3/3" in report
    assert "- Pairs reused: 12/15 (80.00%); scored again: 3." in report
    assert '"device": "cpu"' in report and "Aggregate metrics identical: True" in report


def test_cache_follows_config_and_can_be_disabled(monkeypatch) -> None:
    from eval.rerank_cache import cache_path

    from support_agent.config import REPO_ROOT

    settings = Settings()
    assert cache_path(settings) == REPO_ROOT / settings.index.release.rerank_cache.path
    settings.index.release.rerank_cache.enabled = False
    assert cache_path(settings) is None
