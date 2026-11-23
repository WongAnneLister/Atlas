"""Correctness and efficiency evaluation for the versioned three-layer cache."""

from __future__ import annotations

import argparse
import logging
import math
import statistics
import subprocess
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from langchain_core.messages import HumanMessage

from eval.common import load_items
from eval.e2e_speed import run_config_hash
from support_agent.cache.keys import normalise_query_text
from support_agent.cache.layers import bump_index_revision
from support_agent.cache.metrics import CacheEvent
from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.data.doc_models import write_text
from support_agent.graph.build import build_graph
from support_agent.graph.deps import GraphDeps
from support_agent.infra.redis import KeyValueStore, NullRedis
from support_agent.llm import resolve_model
from support_agent.observability.cost import UsageLedger
from support_agent.retrieval.embed import BgeM3Embedder, Embedder

PAIRS_PATH = REPO_ROOT / "eval" / "drafts" / "cache_near_duplicate_pairs.yaml"
DEFAULT_REPORT = REPO_ROOT / "eval" / "reports" / "cache.md"
DEFAULT_EVAL_FILE = REPO_ROOT / "eval" / "sets" / "smoke.jsonl"


@dataclass(frozen=True)
class ContrastPair:
    id: str
    kind: str
    query_a: str
    query_b: str


def load_contrast_pairs(path: Path = PAIRS_PATH) -> list[ContrastPair]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [ContrastPair(**row) for row in data.get("pairs", [])]


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    ln = math.sqrt(sum(a * a for a in left))
    rn = math.sqrt(sum(b * b for b in right))
    return dot / (ln * rn) if ln and rn else 0.0


def evaluate_near_duplicate_pairs(
    embedder: Embedder,
    pairs: list[ContrastPair],
    *,
    configured_threshold: float,
    sweep: tuple[float, ...] = (0.90, 0.93, 0.95, 0.97, 0.99),
) -> dict[str, Any]:
    texts = [
        text
        for pair in pairs
        for text in (normalise_query_text(pair.query_a), normalise_query_text(pair.query_b))
    ]
    vectors = embedder.embed(texts)
    scored: list[dict[str, Any]] = []
    for index, pair in enumerate(pairs):
        sim = _cosine(vectors[2 * index], vectors[2 * index + 1])
        scored.append(
            {
                "id": pair.id,
                "kind": pair.kind,
                "query_a": pair.query_a,
                "query_b": pair.query_b,
                "similarity": sim,
                "wrong_hit": sim >= configured_threshold,
            }
        )
    sweep_rows = []
    for threshold in sweep:
        hits = sum(1 for row in scored if row["similarity"] >= threshold)
        sweep_rows.append(
            {
                "threshold": threshold,
                "wrong_hits": hits,
                "total": len(scored),
                "wrong_hit_rate": hits / len(scored) if scored else 0.0,
            }
        )
    wrong_hits = sum(1 for row in scored if row["wrong_hit"])
    return {
        "configured_threshold": configured_threshold,
        "total": len(scored),
        "wrong_hits": wrong_hits,
        "wrong_hit_rate": wrong_hits / len(scored) if scored else 0.0,
        "max_similarity": max((row["similarity"] for row in scored), default=0.0),
        "sweep": sweep_rows,
        "rows": sorted(scored, key=lambda row: -row["similarity"]),
    }


def _invoke_once(
    graph: Any, question: str, customer_id: str, extra_state: dict[str, Any] | None = None
) -> tuple[dict[str, Any], float, UsageLedger]:
    usage = UsageLedger()
    payload: dict[str, Any] = {
        "messages": [HumanMessage(content=question)],
        "customer_id": customer_id,
        **(extra_state or {}),
    }
    config: dict[str, Any] = {
        "configurable": {"thread_id": f"cache-eval-{uuid4().hex}"},
        "callbacks": [usage],
    }
    started = time.perf_counter()
    result = graph.invoke(payload, config)
    elapsed = time.perf_counter() - started
    return result, elapsed, usage


def _layer_counts(events: list[CacheEvent]) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter[str]] = {}
    for event in events:
        counts.setdefault(event.layer, Counter())[event.outcome] += 1
    return {layer: dict(counter) for layer, counter in sorted(counts.items())}


def _replay_pass(
    graph: Any, questions: list[tuple[str, str]], customer_id: str
) -> list[dict[str, Any]]:
    rows = []
    for item_id, question in questions:
        result, elapsed, usage = _invoke_once(graph, question, customer_id)
        rows.append(
            {
                "id": item_id,
                "question": question,
                "answer": str(result.get("answer", "")),
                "citations": result.get("citations", []),
                "answer_status": result.get("answer_status"),
                "handoff_reason": getattr(result.get("handoff"), "reason", None),
                "answer_cache_hit": result.get("answer_cache_hit"),
                "cache_events": list(result.get("cache_events", [])),
                "latency_s": elapsed,
                "llm_calls": usage.calls,
                "input_tokens": sum(u.input_tokens for u in usage.by_model.values()),
                "output_tokens": sum(u.output_tokens for u in usage.by_model.values()),
            }
        )
    return rows


def evaluate_replay(
    graph: Any, questions: list[tuple[str, str]], customer_id: str
) -> dict[str, Any]:
    pass1 = _replay_pass(graph, questions, customer_id)
    pass2 = _replay_pass(graph, questions, customer_id)

    mismatches = []
    for left, right in zip(pass1, pass2, strict=True):
        if right["answer_cache_hit"] is not None and (
            left["answer"] != right["answer"]
            or left["citations"] != right["citations"]
            or left["answer_status"] != right["answer_status"]
        ):
            mismatches.append(left["id"])

    p1_lat = [row["latency_s"] for row in pass1]
    p2_lat = [row["latency_s"] for row in pass2]
    p1_tokens = sum(row["input_tokens"] + row["output_tokens"] for row in pass1)
    p2_tokens = sum(row["input_tokens"] + row["output_tokens"] for row in pass2)
    p1_calls = sum(row["llm_calls"] for row in pass1)
    p2_calls = sum(row["llm_calls"] for row in pass2)

    all_p2_events = [ev for row in pass2 for ev in row["cache_events"]]
    return {
        "n_items": len(questions),
        "pass2_answer_hits": sum(1 for row in pass2 if row["answer_cache_hit"] is not None),
        "mismatches_on_hit": mismatches,
        "pass1_mean_latency_s": statistics.mean(p1_lat) if p1_lat else 0.0,
        "pass2_mean_latency_s": statistics.mean(p2_lat) if p2_lat else 0.0,
        "latency_saved_s": sum(p1_lat) - sum(p2_lat),
        "pass1_llm_calls": p1_calls,
        "pass2_llm_calls": p2_calls,
        "llm_calls_saved": p1_calls - p2_calls,
        "pass1_tokens": p1_tokens,
        "pass2_tokens": p2_tokens,
        "tokens_saved": p1_tokens - p2_tokens,
        "pass2_layer_counts": _layer_counts(all_p2_events),
    }


def evaluate_staleness(
    graph: Any,
    store: KeyValueStore,
    settings: Settings,
    question: str,
    customer_id: str,
    *,
    bump_build: Any | None = None,
) -> dict[str, Any]:
    first, _, _ = _invoke_once(graph, question, customer_id)
    warm, _, _ = _invoke_once(graph, question, customer_id)
    if bump_build is not None:
        bump_build()
    bump_index_revision(store, settings.cache)
    after, _, _ = _invoke_once(graph, question, customer_id)
    return {
        "question": question,
        "warm_hit": warm.get("answer_cache_hit") is not None,
        "after_invalidation_miss": after.get("answer_cache_hit") is None,
        "first_answer": str(first.get("answer", "")),
        "after_answer": str(after.get("answer", "")),
        "passed": (
            warm.get("answer_cache_hit") is not None and after.get("answer_cache_hit") is None
        ),
    }


def evaluate_isolation(
    graph: Any,
    question: str,
    *,
    customer_a: str = "CUST-0001",
    customer_b: str = "CUST-0002",
    canary: str = "CANARY-ORDER-SECRET-991",
) -> dict[str, Any]:
    res_a, _, _ = _invoke_once(
        graph,
        f"{question} (regarding ORD-000065)",
        customer_a,
        extra_state={"order_context": {"order_id": "ORD-000065", "note": canary}},
    )
    res_b, _, _ = _invoke_once(graph, question, customer_b)
    leaked = canary in str(res_b.get("answer", ""))
    a_bypassed = res_a.get("answer_cache_hit") is None and any(
        ev.layer == "answer" and ev.outcome == "bypass" for ev in res_a.get("cache_events", [])
    )
    return {
        "customer_a_bypassed": a_bypassed,
        "customer_b_leaked_canary": leaked,
        "passed": a_bypassed and not leaked,
    }


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "-c", f"safe.directory={REPO_ROOT}", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def render_report(
    settings: Settings,
    *,
    mode: str,
    eval_file: str,
    replay: dict[str, Any],
    staleness: dict[str, Any],
    isolation: dict[str, Any],
    near_duplicate: dict[str, Any],
) -> str:
    fast_name, _ = resolve_model("fast", settings.llm)
    main_name, _ = resolve_model("main", settings.llm)
    lines = [
        "# Cache correctness and efficiency report",
        "",
        "Generated by `make eval-cache`. Do not edit by hand.",
        "",
        f"- Mode: `{mode}`",
        f"- Git SHA: `{_git_sha()}`",
        f"- Config hash: `{run_config_hash(settings)}`",
        f"- Eval file: `{eval_file}`",
        f"- Models: fast=`{fast_name or 'unset'}`, main=`{main_name or 'unset'}`, "
        f"embed=`{settings.retrieval.embedding_model}@{settings.retrieval.embedding_revision}`",
        f"- Date (UTC): {datetime.now(UTC).date().isoformat()}",
        "",
        "## 1. Two-pass replay (exact cache)",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Items replayed | {replay['n_items']} |",
        f"| Pass-2 answer cache hits | {replay['pass2_answer_hits']} |",
        f"| Outcome mismatches on hit | {len(replay['mismatches_on_hit'])} |",
        f"| Pass-1 mean latency (s) | {replay['pass1_mean_latency_s']:.4f} |",
        f"| Pass-2 mean latency (s) | {replay['pass2_mean_latency_s']:.4f} |",
        f"| Total latency saved (s) | {replay['latency_saved_s']:.4f} |",
        f"| Pass-1 LLM calls | {replay['pass1_llm_calls']} |",
        f"| Pass-2 LLM calls | {replay['pass2_llm_calls']} |",
        f"| LLM calls saved | {replay['llm_calls_saved']} |",
        f"| Pass-1 tokens | {replay['pass1_tokens']} |",
        f"| Pass-2 tokens | {replay['pass2_tokens']} |",
        f"| Tokens saved | {replay['tokens_saved']} |",
        "",
        "### Pass-2 layer counts",
        "",
        "| Layer | Hits | Misses | Bypasses | Errors |",
        "|---|---:|---:|---:|---:|",
    ]
    for layer, counts in replay["pass2_layer_counts"].items():
        lines.append(
            f"| {layer} | {counts.get('hit', 0)} | {counts.get('miss', 0)} | "
            f"{counts.get('bypass', 0)} | {counts.get('error', 0)} |"
        )
    if not replay["pass2_layer_counts"]:
        lines.append("| (none) | 0 | 0 | 0 | 0 |")

    lines.extend(
        [
            "",
            "## 2. Staleness (invalidation on index update)",
            "",
            f"- Question: `{staleness['question']}`",
            f"- Warm pass hit cache: `{staleness['warm_hit']}`",
            f"- Post-invalidation pass missed cache: `{staleness['after_invalidation_miss']}`",
            f"- Result: **{'PASS' if staleness['passed'] else 'FAIL'}**",
            "",
            "## 3. Cross-customer isolation (canary check)",
            "",
            f"- Customer A (with order context) bypassed answer cache: "
            f"`{isolation['customer_a_bypassed']}`",
            f"- Customer B saw Customer A canary: `{isolation['customer_b_leaked_canary']}`",
            f"- Result: **{'PASS' if isolation['passed'] else 'FAIL'}**",
            "",
            "## 4. Near-duplicate answer cache wrong-hit evaluation",
            "",
            f"- Contrast pairs tested: {near_duplicate['total']} "
            f"(different-answer pairs from `eval/drafts/cache_near_duplicate_pairs.yaml`)",
            f"- Configured threshold: `{near_duplicate['configured_threshold']}`",
            f"- Wrong hits at configured threshold: "
            f"**{near_duplicate['wrong_hits']}/{near_duplicate['total']}** "
            f"({near_duplicate['wrong_hit_rate'] * 100:.2f}%)",
            f"- Max cosine similarity across contrast pairs: "
            f"`{near_duplicate['max_similarity']:.4f}`",
            f"- Decision: near-duplicate mode stays "
            f"**{'OFF' if near_duplicate['wrong_hits'] > 0 else 'review-eligible'}** "
            f"(`cache.answer.near_duplicate.enabled: false`).",
            "",
            "| Threshold | Wrong hits | Total | Wrong-hit rate |",
            "|---:|---:|---:|---:|",
        ]
    )
    for row in near_duplicate["sweep"]:
        lines.append(
            f"| {row['threshold']:.2f} | {row['wrong_hits']} | {row['total']} | "
            f"{row['wrong_hit_rate'] * 100:.2f}% |"
        )
    lines.extend(
        [
            "",
            "### Highest-similarity contrast pairs",
            "",
            "| ID | Kind | Cosine | Query A | Query B |",
            "|---|---|---:|---|---|",
        ]
    )
    for row in near_duplicate["rows"][:8]:
        lines.append(
            f"| {row['id']} | {row['kind']} | {row['similarity']:.4f} | "
            f"{row['query_a']} | {row['query_b']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate cache correctness and efficiency.")
    parser.add_argument("--eval-file", type=Path, default=DEFAULT_EVAL_FILE)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--pairs-only", action="store_true")
    args = parser.parse_args(argv)

    settings = get_settings().model_copy(deep=True)
    settings.cache.enabled = True
    pairs = load_contrast_pairs()
    embedder = BgeM3Embedder(settings.retrieval)
    near_dup = evaluate_near_duplicate_pairs(
        embedder,
        pairs,
        configured_threshold=settings.cache.answer.near_duplicate.similarity_threshold,
    )
    if args.pairs_only:
        log = logging.getLogger(__name__)
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        for row in near_dup["sweep"]:
            log.info(
                "threshold=%.2f wrong_hits=%d/%d (%.1f%%)",
                row["threshold"],
                row["wrong_hits"],
                row["total"],
                row["wrong_hit_rate"] * 100,
            )
        return 0

    items = load_items(args.eval_file)
    if args.limit is not None:
        items = items[: args.limit]
    questions = [(item.id, item.question) for item in items]

    store: KeyValueStore = NullRedis()
    deps = GraphDeps(settings=settings, cache_store=store, cache_embedder=embedder)
    try:
        graph = build_graph(deps)
        replay = evaluate_replay(graph, questions, settings.evaluation.customer_id)
        staleness = evaluate_staleness(
            graph,
            store,
            settings,
            "What is the return window for the generic store?",
            settings.evaluation.customer_id,
        )
        isolation = evaluate_isolation(graph, "What is the return window for the generic store?")
    finally:
        deps.close()

    report = render_report(
        settings,
        mode="live",
        eval_file=str(args.eval_file.relative_to(REPO_ROOT)),
        replay=replay,
        staleness=staleness,
        isolation=isolation,
        near_duplicate=near_dup,
    )
    write_text(args.report, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
