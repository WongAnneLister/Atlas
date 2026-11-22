"""Collect and compare release evidence without generating answers."""

import argparse
import sys
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import sleep as sleep_seconds
from typing import Literal
from uuid import uuid4

from eval.common import load_items
from eval.gate import GateRules, load_rules
from eval.paired import Comparison, compare, comparison_lines
from eval.registry import file_hash, load_registry
from eval.rerank_cache import CachedReranker, ScoreCache, cache_path, score_profile
from eval.run_record import (
    RUNS,
    DatasetVersion,
    Run,
    RunItem,
    RunManifest,
    format_summary,
    git,
    is_dirty,
    read_run,
    write_run,
)
from eval.schema import EvalItem
from eval.smoke import load_smoke_spec
from eval.sweep import production_retrieval
from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.data.doc_models import digest, json_text, write_text
from support_agent.gate.evidence import evaluate
from support_agent.reliability.guards import DependencyUnavailable, diagnostic_type
from support_agent.reliability.retry import retry_call
from support_agent.retrieval.factory import build_retriever
from support_agent.retrieval.filters import RetrievalFilters
from support_agent.retrieval.milvus_store import MilvusStore, milvus_transport_failure
from support_agent.retrieval.rerank import BgeReranker
from support_agent.retrieval.types import RetrievedChunk, Retriever

_ANSWER_METRICS = ("hit_at_5", "rr_at_5", "gate_pass")
_NOANSWER = "noanswer_gate_pass"


@dataclass(frozen=True)
class ReleaseSet:
    items: list[EvalItem]
    datasets: dict[str, DatasetVersion]
    split: str

    @property
    def item_set_hash(self) -> str:
        return digest(json_text([item.model_dump(mode="json") for item in self.items]))


def load_release_set(settings: Settings) -> ReleaseSet:
    registry = load_registry()
    datasets = {}
    items = []
    for split in settings.index.release.sets:
        name = "eval_v1" if split == "dev" else "smoke"
        entry = registry[name]
        path = REPO_ROOT / entry.path
        if file_hash(path) != entry.sha256:
            raise ValueError(f"Invalid frozen dataset: {name}")
        selected = load_items(path)
        if split == "dev":
            selected = [item for item in selected if item.split == "dev"]
        elif any(item.split != "test" for item in selected) or {
            item.id for item in selected
        } != set(load_smoke_spec().item_ids):
            raise ValueError("Release smoke items differ from the frozen selection")
        items.extend(selected)
        datasets[name] = DatasetVersion(version=entry.version, sha256=entry.sha256)
    if not items or len({item.id for item in items}) != len(items):
        raise ValueError("Release set must contain unique item IDs")
    if {item.answerable for item in items} != {True, False}:
        raise ValueError("Release requires answerable and no-answer items")
    return ReleaseSet(
        sorted(items, key=lambda item: item.id), datasets, "-".join(settings.index.release.sets)
    )


def absolute_ids(release_set: ReleaseSet, settings: Settings) -> frozenset[str]:
    """No-answer items whose gate result must be zero with no reference to the live build.

    The gate threshold is tuned on dev, so dev is where zero gate passes is a calibrated claim.
    Test items only have to avoid new passes against the live build (see gate_rules.yaml).
    """
    splits = set(settings.index.release.absolute_splits)
    return frozenset(
        item.id for item in release_set.items if not item.answerable and item.split in splits
    )


def evidence_config_hash(settings: Settings) -> str:
    milvus = settings.milvus.model_dump(mode="json", exclude={"collection", "uri"})
    return digest(
        json_text(
            {
                "retrieval": settings.retrieval.model_dump(mode="json"),
                "gate": settings.gate.model_dump(mode="json"),
                "milvus": milvus,
                "hit_k": settings.index.release.hit_k,
                "policy_day": settings.orders.today.isoformat(),
                "policy_open_end_day": settings.policy_versions.open_end_day,
                "catalog_categories": settings.data.docs.product_categories,
            }
        )
    )


def _collect_item(
    retriever: Retriever,
    item: EvalItem,
    settings: Settings,
    sleep: Callable[[float], None] = sleep_seconds,
) -> RunItem:
    row = RunItem(id=item.id, group=item.group, answerable=item.answerable)
    retries = 0

    def count_retry() -> None:
        nonlocal retries
        retries += 1

    def search(_remaining: float) -> tuple[list[RetrievedChunk], RetrievalFilters | None, bool]:
        # Only a broken link is retried; any other error is recorded on the first attempt.
        try:
            return production_retrieval(retriever, item.question, settings)
        except Exception as error:
            if milvus_transport_failure(error):
                raise DependencyUnavailable("milvus", error) from error
            raise

    try:
        chunks, filters, filters_applied = retry_call(
            search,
            policy=settings.index.release.retry,
            is_idempotent=True,
            sleep=sleep,
            on_retry=count_retry,
        )
        gate = evaluate(item.question, chunks, settings.gate)
    except Exception as error:
        row.payload["error_type"] = diagnostic_type(error)
        if retries:
            row.payload["retries"] = retries
        return row
    top = chunks[: settings.index.release.hit_k]
    row.payload = {
        "gate_score": gate.score,
        "top_chunk_ids": [chunk.chunk_id for chunk in top],
        "filters": filters.model_dump(mode="json") if filters is not None else None,
        "filters_applied": filters_applied,
    }
    if retries:
        row.payload["retries"] = retries
    if item.answerable:
        rank = next(
            (i for i, chunk in enumerate(top, 1) if chunk.section_id in item.gold_sections), None
        )
        row.metrics = {
            "hit_at_5": rank is not None,
            "rr_at_5": 1 / rank if rank else 0.0,
            "gate_pass": gate.passed,
        }
    else:
        row.metrics = {_NOANSWER: gate.passed}
    return row


def collect_run(
    settings: Settings,
    collection: str,
    *,
    build_id: str | None = None,
    fingerprint: str | None = None,
    release_set: ReleaseSet | None = None,
    reranker_device: str | None = None,
    retriever: Retriever | None = None,
    reranker: CachedReranker | None = None,
    run_root: Path = RUNS,
) -> Path:
    """Collect one evidence run; an injected ``retriever`` may share its ``reranker`` counts."""
    config = settings.model_copy(deep=True)
    config.milvus.collection = collection
    if reranker_device is not None:
        config.retrieval.reranker_device = reranker_device
    selected = release_set or load_release_set(config)
    started = datetime.now(UTC)
    dirty = is_dirty()
    sha = git("rev-parse", "HEAD")
    if retriever is None:
        path = cache_path(config)
        cache = ScoreCache(path, score_profile(config)) if path else None
        store = MilvusStore(config)
        try:
            reranker = CachedReranker(BgeReranker(config.retrieval), cache)
            retriever = build_retriever(
                "hybrid_rerank", settings=config, store=store, reranker=reranker
            )
            rows = [_collect_item(retriever, item, config) for item in selected.items]
        finally:
            store.close()
            if cache is not None:
                cache.close()
    else:
        rows = [_collect_item(retriever, item, config) for item in selected.items]
    retrieval = config.retrieval
    return write_run(
        RunManifest(
            kind="index_release",
            split=selected.split,
            git_sha=sha,
            config_hash=evidence_config_hash(config),
            models={
                "embedding": f"{retrieval.embedding_model}@{retrieval.embedding_revision}",
                "reranker": f"{retrieval.reranker_model}@{retrieval.reranker_revision}",
            },
            datasets=selected.datasets,
            seed=config.eval.stats.seed,
            dirty=dirty,
            started_at=started,
            ended_at=datetime.now(UTC),
            cost_usd=None,
            cost_note="retrieval and evidence gate only",
            command=["make", "eval-index-release"],
            source={
                "collection": collection,
                "build_id": build_id,
                "fingerprint": fingerprint,
                "item_set_hash": selected.item_set_hash,
                "reranker_device": config.retrieval.reranker_device,
                # Counts (query, passage) logits; the cache never changes a row.
                "rerank_scores": reranker.summary() if reranker else None,
            },
        ),
        rows,
        root=run_root,
        suffix=uuid4().hex,
    )


def find_live_run(
    settings: Settings,
    *,
    build_id: str,
    release_set: ReleaseSet,
    run_root: Path = RUNS,
    fingerprint: str | None = None,
    collection: str | None = None,
) -> Path | None:
    expected = evidence_config_hash(settings)
    for path in sorted(run_root.glob("index-release-*"), reverse=True):
        try:
            run = read_run(path)
        except (OSError, ValueError):
            continue
        source = run.manifest.source
        if (
            run.manifest.kind == "index_release"
            and run.manifest.dirty is False
            and run.manifest.config_hash == expected
            and source.get("build_id") == build_id
            and source.get("item_set_hash") == release_set.item_set_hash
            and run.manifest.datasets == release_set.datasets
            and (fingerprint is None or source.get("fingerprint") == fingerprint)
            and (collection is None or source.get("collection") == collection)
            and {row.id for row in run.items} == {item.id for item in release_set.items}
            and all(not row.payload.get("error_type") for row in run.items)
        ):
            return path
    return None


@dataclass
class ReleaseDecision:
    outcome: Literal["release", "refuse", "invalid"]
    reasons: list[str] = field(default_factory=list)
    comparisons: list[Comparison] = field(default_factory=list)
    changes: dict[str, list[str]] = field(default_factory=dict)
    override_reason: str | None = None
    candidate: RunManifest | None = None
    summaries: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def markdown(self) -> str:
        outcome = "Invalid run" if self.outcome == "invalid" else self.outcome.capitalize()
        lines = [f"# Index release — {outcome}", "", *(f"- {reason}" for reason in self.reasons)]
        if self.candidate:
            manifest = self.candidate
            lines.extend(
                [
                    "",
                    f"- Candidate collection: {manifest.source.get('collection')}",
                    f"- Git SHA: {manifest.git_sha}",
                    f"- Config hash: {manifest.config_hash}",
                    f"- Split: {manifest.split}",
                    f"- UTC date: {manifest.started_at}",
                    f"- Models: {', '.join(manifest.models.values())}",
                    f"- Dataset versions: {manifest.datasets}",
                ]
            )
        if self.summaries:
            lines.extend(
                ["", *[f"- {name}: {summary}" for name, summary in self.summaries.items()]]
            )
        if self.notes:
            lines.extend(["", *(f"- Note: {note}" for note in self.notes)])
        if self.override_reason:
            lines.extend(["", f"Paired override reason: {self.override_reason}"])
        if self.comparisons:
            lines.extend(["", *comparison_lines(self.comparisons)])
        for metric, ids in self.changes.items():
            lines.extend(["", f"- {metric}: {', '.join(ids)}"])
        return "\n".join(lines) + "\n"


def _validate_rows(run: Run, name: str, rules: GateRules) -> str | None:
    if (
        run.manifest.kind != "index_release"
        or not run.items
        or len({row.id for row in run.items}) != len(run.items)
    ):
        return f"{name} does not contain unique index-release observations."
    errors = sum(bool(row.payload.get("error_type")) for row in run.items)
    if errors / len(run.items) > rules.promotion_max_error_rate:
        return f"{name} retrieval errors on {errors}/{len(run.items)} items exceed the limit."
    if not any(row.answerable is False for row in run.items):
        return f"{name} has no no-answer observations."
    for row in run.items:
        if not row.payload.get("error_type"):
            expected = set(_ANSWER_METRICS) if row.answerable else {_NOANSWER}
            if (
                row.answerable is None
                or set(row.metrics) != expected
                or any(type(row.metrics[key]) is not bool for key in expected - {"rr_at_5"})
                or (
                    "rr_at_5" in expected
                    and (
                        type(row.metrics["rr_at_5"]) is bool or not 0 <= row.metrics["rr_at_5"] <= 1
                    )
                )
            ):
                return f"{name} contains malformed metrics for {row.id}."
    return None


def evaluate_release(
    candidate: Run,
    live: Run | None = None,
    *,
    rules: GateRules | None = None,
    override_reason: str | None = None,
    absolute: Collection[str] | None = None,
) -> ReleaseDecision:
    """Judge a candidate run; ``absolute`` names the zero-pass no-answer items (None: all)."""
    rules = rules or load_rules()
    for name, run in (("Candidate", candidate), ("Live", live)):
        if run is not None and (invalid := _validate_rows(run, name, rules)):
            return ReleaseDecision("invalid", [invalid])
    no_answer = [row for row in candidate.items if row.answerable is False]
    scope = set(absolute) if absolute is not None else {row.id for row in no_answer}
    passing = [row.id for row in no_answer if row.metrics.get(_NOANSWER) is True]
    unsafe = [row_id for row_id in passing if row_id in scope]
    relative = [row_id for row_id in passing if row_id not in scope]
    unknown = [row.id for row in no_answer if row.payload.get("error_type")]
    refusals = []
    if len(unsafe) > rules.index_release.noanswer_gate_pass_max:
        refusals.append(f"No-answer gate passed: {', '.join(unsafe)}.")
    if unknown:
        refusals.append(f"No-answer gate could not be verified: {', '.join(unknown)}.")
    decision = ReleaseDecision(
        "refuse" if refusals else "release",
        refusals,
        candidate=candidate.manifest,
        summaries={
            name: format_summary(summary, rate=name != "rr_at_5")
            for name, summary in candidate.metrics.metrics.items()
        },
    )
    if live is None:
        if relative:
            decision.notes.append(
                "No live build to compare; these no-answer items pass the gate and are "
                f"recorded, not judged: {', '.join(relative)}."
            )
        return decision
    if (
        not candidate.manifest.source.get("item_set_hash")
        or candidate.manifest.source.get("item_set_hash")
        != live.manifest.source.get("item_set_hash")
        or live.manifest.datasets != candidate.manifest.datasets
        or {row.id: (row.answerable, row.group) for row in live.items}
        != {row.id: (row.answerable, row.group) for row in candidate.items}
    ):
        return ReleaseDecision("invalid", ["Release sets or labels differ."])
    metrics = {metric: rules.metrics[metric] for metric in (*_ANSWER_METRICS, _NOANSWER)}
    decision.comparisons = compare(live, candidate, metrics)
    if {item.name for item in decision.comparisons} != metrics.keys():
        return ReleaseDecision("invalid", ["A metric has no paired observations."])
    previous = {row.id: row for row in live.items}
    new = [row_id for row_id in relative if previous[row_id].metrics.get(_NOANSWER) is not True]
    known = [row_id for row_id in relative if row_id not in new]
    if len(new) > rules.index_release.noanswer_new_pass_max:
        # Not covered by --override-reason: a new no-answer pass is a safety change.
        decision.outcome = "refuse"
        decision.reasons.append(f"No-answer item newly passes the gate: {', '.join(new)}.")
    if known:
        decision.notes.append(
            "These no-answer items already pass the gate on the live build; a later "
            f"check, not this one, stops them: {', '.join(known)}."
        )
    for metric in metrics:
        changes = [
            row.id
            for row in candidate.items
            if metric in row.metrics
            and metric in previous[row.id].metrics
            and row.metrics[metric] != previous[row.id].metrics[metric]
        ]
        if changes:
            decision.changes[metric] = sorted(changes)
    worse = [
        item.name
        for item in decision.comparisons
        if item.verdict == "worse" and metrics[item.name].blocking
    ]
    if worse:
        decision.override_reason = override_reason.strip() if override_reason else None
        decision.reasons.extend(f"Paired regression: {name}." for name in worse)
        if not decision.override_reason:
            decision.outcome = "refuse"
    return decision


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    collect = commands.add_parser("collect")
    collect.add_argument("collection")
    collect.add_argument("--reranker-device")
    cache = collect.add_mutually_exclusive_group()
    cache.add_argument("--rerank-cache", type=Path, help="score cache file (default: config)")
    cache.add_argument("--no-rerank-cache", action="store_true", help="score every pair")
    check = commands.add_parser("check")
    check.add_argument("candidate", type=Path)
    check.add_argument("--live", type=Path)
    check.add_argument("--output", type=Path)
    check.add_argument("--override-reason")
    args = parser.parse_args()
    if args.command == "collect":
        settings = get_settings().model_copy(deep=True)
        cache_settings = settings.index.release.rerank_cache
        if args.no_rerank_cache:
            cache_settings.enabled = False
        elif args.rerank_cache:
            cache_settings.enabled, cache_settings.path = True, str(args.rerank_cache)
        path = collect_run(settings, args.collection, reranker_device=args.reranker_device)
        sys.stdout.write(f"{path}\n")
        return 0
    settings = get_settings()
    result = evaluate_release(
        read_run(args.candidate),
        read_run(args.live) if args.live else None,
        override_reason=args.override_reason,
        absolute=absolute_ids(load_release_set(settings), settings),
    )
    sys.stdout.write(result.markdown())
    if args.output:
        write_text(args.output, result.markdown())
    return int(result.outcome != "release")


if __name__ == "__main__":
    raise SystemExit(main())
