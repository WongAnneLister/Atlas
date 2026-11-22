"""Opt-in speed-ups for real-model end-to-end runs that leave every measured value alone.

Both are off by default:

- A rerank score cache. It reuses cross-encoder logits from the release-evidence file,
  keyed exactly as that path keys them: reranker model, revision, device, fp16, max tokens,
  batch size, key package versions, the query text and the passage text hash.
- Bounded item concurrency (``--workers N``). Items then share the one reranker worker and
  the LLM API, so per-item latency includes queueing. Such runs are marked as having
  latency that is not comparable, and comparisons leave latency out.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from contextvars import copy_context
from dataclasses import dataclass, field
from typing import Any, TypeVar

from eval.rerank_cache import (
    CachedReranker,
    LogitScorer,
    ScoreCache,
    display_path,
    score_profile,
    shared_cache_path,
)
from eval.run_record import Run
from support_agent.config import Settings
from support_agent.data.doc_models import digest, json_text
from support_agent.retrieval.rerank import BgeReranker, Reranker

Item = TypeVar("Item")
Result = TypeVar("Result")
Rule = TypeVar("Rule")

LATENCY_METRIC_PREFIXES = ("latency_", "first_token_")
NOT_COMPARABLE = "not comparable: items ran concurrently"


def run_config_hash(settings: Settings) -> str:
    """Config hash of an e2e run. Speed switches change no value, so they are left out."""
    return digest(json_text(settings.model_dump(mode="json", exclude={"eval": {"e2e_speed"}})))


@dataclass(frozen=True)
class SpeedOptions:
    workers: int = 1
    rerank_cache: bool = False


def add_speed_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="items in flight at once (default 1); latency is not comparable above 1",
    )
    cache = parser.add_mutually_exclusive_group()
    cache.add_argument(
        "--rerank-cache",
        dest="rerank_cache",
        action="store_true",
        default=None,
        help="reuse cross-encoder logits from the release-evidence cache file",
    )
    cache.add_argument(
        "--no-rerank-cache",
        dest="rerank_cache",
        action="store_false",
        help="score every (query, passage) pair (overrides eval.e2e_speed.rerank_cache)",
    )


def speed_options(
    args: argparse.Namespace, settings: Settings, parser: argparse.ArgumentParser
) -> SpeedOptions:
    speed = settings.eval.e2e_speed
    options = SpeedOptions(
        workers=args.workers,
        rerank_cache=speed.rerank_cache if args.rerank_cache is None else args.rerank_cache,
    )
    if not 1 <= options.workers <= speed.max_workers:
        parser.error(
            f"--workers must be between 1 and {speed.max_workers} (eval.e2e_speed.max_workers)"
        )
    if settings.chaos.enabled and options != SpeedOptions():
        parser.error("Chaos runs stay serial and uncached; seeded faults follow call order")
    return options


@dataclass
class RerankScores:
    """Builds cache-backed rerankers for GraphDeps and counts where their logits came from."""

    cache: ScoreCache | None
    scorer: Callable[[], LogitScorer]
    rerankers: list[CachedReranker] = field(default_factory=list)

    def factory(self) -> Callable[[], Reranker] | None:
        """A ``GraphDeps.reranker_factory``; None keeps the default uncached reranker."""
        cache = self.cache
        if cache is None:
            return None

        def build() -> Reranker:
            reranker = CachedReranker(self.scorer(), cache)
            self.rerankers.append(reranker)
            return reranker

        return build

    def summary(self) -> dict[str, Any] | None:
        if self.cache is None:
            return None
        return {
            "cache": display_path(self.cache.path),
            "profile": self.cache.profile.key,
            "from_cache": sum(reranker.from_cache for reranker in self.rerankers),
            "scored": sum(reranker.scored for reranker in self.rerankers),
        }


@contextmanager
def rerank_scores(
    settings: Settings,
    enabled: bool,
    *,
    scorer: Callable[[], LogitScorer] | None = None,
    cache: ScoreCache | None = None,
) -> Iterator[RerankScores]:
    """Open the shared logit file when ``enabled``; the cache never changes a ranking."""
    build = scorer or (lambda: BgeReranker(settings.retrieval))
    if not enabled:
        yield RerankScores(None, build)
        return
    opened = cache or ScoreCache(shared_cache_path(settings), score_profile(settings))
    try:
        yield RerankScores(opened, build)
    finally:
        if cache is None:
            opened.close()


def merge_rerank_scores(
    saved: Mapping[str, Any] | None, current: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    """Add this session's counts to a resumed run's counts."""
    if saved is None or current is None:
        kept = current if current is not None else saved
        return dict(kept) if kept is not None else None
    if saved.get("profile") != current.get("profile"):
        raise ValueError("Rerank cache profile changed during a resumed run; choose a fresh output")
    return {
        **current,
        "from_cache": int(saved["from_cache"]) + int(current["from_cache"]),
        "scored": int(saved["scored"]) + int(current["scored"]),
    }


def run_items(
    items: Sequence[Item],
    work: Callable[[Item], Result],
    *,
    workers: int,
    done: Callable[[Item, Result], None],
) -> None:
    """Run ``work`` on every item, at most ``workers`` at a time.

    ``done`` runs on the calling thread in completion order. Callers key results by item id
    and save them in input order, so a saved run never depends on scheduling. After the
    first failure no new item starts; items already running finish and reach ``done``,
    then the failure is raised.
    """
    if workers < 1:
        raise ValueError("workers must be positive")
    if workers == 1:
        for item in items:
            done(item, work(item))
        return
    error: BaseException | None = None
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="atlas-eval-item")
    try:
        futures = {pool.submit(copy_context().run, work, item): item for item in items}
        for future in as_completed(futures):
            if future.cancelled():
                continue
            failure = future.exception()
            if failure is not None:
                if error is None:
                    error = failure
                    for pending in futures:
                        pending.cancel()
                continue
            done(futures[future], future.result())
    except BaseException:
        pool.shutdown(wait=True, cancel_futures=True)
        raise
    pool.shutdown(wait=True)
    if error is not None:
        raise error


def latency_comparable(source: Mapping[str, Any]) -> bool:
    """False when a run's items ran concurrently; older runs were serial."""
    return source.get("latency_comparable", True) is not False


def is_latency_metric(name: str) -> bool:
    return name.startswith(LATENCY_METRIC_PREFIXES)


def speed_lines(source: Mapping[str, Any]) -> list[str]:
    """Report lines that say how a run was collected and whether its latency compares."""
    workers = source.get("workers", 1)
    lines = [f"- Item workers: {workers}"]
    if not latency_comparable(source):
        lines.append(
            "- Latency is not comparable with serial runs: items shared the reranker and the "
            "LLM API, so each latency includes time spent waiting for the others."
        )
    scores = source.get("rerank_scores")
    if not scores:
        lines.append("- Rerank score cache: off (every pair scored by the cross-encoder)")
    else:
        total = int(scores["from_cache"]) + int(scores["scored"])
        lines.append(
            f"- Rerank score cache: on (`{scores['cache']}`, profile `{scores['profile']}`); "
            f"{scores['from_cache']}/{total} logits read from the cache, {scores['scored']} scored"
        )
    return lines


def comparable_rules(rules: Mapping[str, Rule], *runs: Run) -> tuple[dict[str, Rule], str | None]:
    """Drop latency rules when any run collected items concurrently, and say why."""
    concurrent = [run for run in runs if not latency_comparable(run.manifest.source)]
    if not concurrent:
        return dict(rules), None
    workers = ", ".join(str(run.manifest.source.get("workers", "unknown")) for run in concurrent)
    kept = {name: rule for name, rule in rules.items() if not is_latency_metric(name)}
    return kept, f"Latency not compared: a run collected items concurrently (workers {workers})."
