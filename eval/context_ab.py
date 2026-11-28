"""Four-arm prefix-cache A/B experiment (sliding, rolling, chunked, chunked_nocache)."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from eval.e2e_eval import _model_names
from eval.e2e_speed import run_config_hash
from eval.run_health import INVALID_RUN_STATUS, invalid_arms_message
from eval.run_record import is_dirty
from eval.sim.build_scenarios import DEFAULT_OUTPUT as DEFAULT_SCENARIOS
from eval.sim.build_scenarios import load_scenarios
from eval.sim.metrics import aggregate_evaluations, evaluate_transcript
from eval.sim.models import ConversationTranscript, Scenario
from eval.sim.run import run_suite
from eval.sim.user import UserSimulator, build_simulator_model
from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.context.settings import ContextStrategy
from support_agent.data.doc_models import write_text
from support_agent.graph.deps import GraphDeps
from support_agent.orders.service import OrderService

DEFAULT_REPORT = REPO_ROOT / "eval" / "reports" / "context_ab.md"
DEFAULT_CHART = REPO_ROOT / "eval" / "reports" / "context_ab_cost.png"
DEFAULT_RUN_ROOT = REPO_ROOT / "eval" / "runs"

STRATEGIES: tuple[ContextStrategy, ...] = ("sliding", "rolling", "chunked", "chunked_nocache")


def run_provenance(settings: Settings, simulator_model: str) -> dict[str, Any]:
    """What a later re-score needs to trust this run: code, config, models and date."""
    return {
        "git_sha": _git_sha(),
        "dirty": _dirty_at_start(),
        "config_hash": run_config_hash(settings),
        "models": _model_names(settings),
        "simulator_model": simulator_model,
        "date": datetime.now(UTC).isoformat(),
    }


@lru_cache(maxsize=1)
def _dirty_at_start() -> bool:
    """Tree state when the run began; outputs written into the repo must not flip it."""
    return is_dirty()


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "-c", f"safe.directory={REPO_ROOT}", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def decompose_cost(
    calls: list[dict[str, Any]],
    *,
    cache_read_multiplier: float = 0.1,
    cache_write_multiplier: float = 1.0,
    ignore_cache_discount: bool = False,
) -> dict[str, float]:
    """Decompose token cost into uncached input, cache writes, cache reads, and output."""
    total_in = sum(int(c.get("input_tokens", 0) or 0) for c in calls)
    cache_read = sum(int(c.get("cache_read_tokens", 0) or 0) for c in calls)
    cache_write = sum(int(c.get("cache_write_tokens", 0) or 0) for c in calls)
    output_tok = sum(int(c.get("output_tokens", 0) or 0) for c in calls)
    uncached_in = max(0, total_in - cache_read - cache_write)
    eff_read_mult = 1.0 if ignore_cache_discount else cache_read_multiplier
    effective_input_units = (
        uncached_in + cache_write * cache_write_multiplier + cache_read * eff_read_mult
    )
    return {
        "total_input_tokens": float(total_in),
        "uncached_input_tokens": float(uncached_in),
        "cache_write_tokens": float(cache_write),
        "cache_read_tokens": float(cache_read),
        "output_tokens": float(output_tok),
        "effective_input_units": float(effective_input_units),
        "cache_hit_ratio": (cache_read / total_in) if total_in > 0 else 0.0,
    }


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _prefix_change_rate(transcripts: list[ConversationTranscript]) -> float | None:
    """Fraction of consecutive turns where the main node's stable prefix (L0..L2) changed.

    The full prefix hash also covers L3 history, which grows every turn, so it changes on
    every turn for every strategy. Only L0..L2 is meant to stay fixed between compactions.
    Records written before `stable_hash` existed return None.
    """
    transitions = 0
    changes = 0
    for tr in transcripts:
        prev_hash: str | None = None
        for turn in tr.turns:
            hashes = [
                str(c.get("stable_hash", ""))
                for c in turn.context_calls
                if c.get("node") in {"answer", "tools", "decide", "rewrite", "complaint"}
                and c.get("stable_hash")
            ]
            if not hashes:
                continue
            cur = hashes[-1]
            if prev_hash is not None:
                transitions += 1
                if cur != prev_hash:
                    changes += 1
            prev_hash = cur
    return (changes / transitions) if transitions else None


def _arm_metrics(
    strategy: ContextStrategy,
    transcripts: list[ConversationTranscript],
    agg: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    all_calls = [c for tr in transcripts for t in tr.turns for c in t.context_calls]
    cost = decompose_cost(
        all_calls,
        cache_read_multiplier=settings.context.cache_read_multiplier,
        cache_write_multiplier=settings.context.cache_write_multiplier,
        ignore_cache_discount=(strategy == "chunked_nocache"),
    )
    history_tokens = [
        int((c.get("by_layer") or {}).get("L3_history", 0))
        + int((c.get("by_layer") or {}).get("L2_compacted", 0))
        for c in all_calls
        if c.get("node") in {"answer", "tools", "decide", "rewrite"}
    ]
    latencies = sorted(t.latency_s for tr in transcripts for t in tr.turns)
    p50 = latencies[len(latencies) // 2] if latencies else 0.0
    p95 = latencies[min(len(latencies) - 1, int(0.95 * (len(latencies) - 1)))] if latencies else 0.0

    by_turn: dict[int, list[float]] = defaultdict(list)
    for tr in transcripts:
        running = 0.0
        for turn in tr.turns:
            tc = decompose_cost(
                turn.context_calls,
                cache_read_multiplier=settings.context.cache_read_multiplier,
                cache_write_multiplier=settings.context.cache_write_multiplier,
                ignore_cache_discount=(strategy == "chunked_nocache"),
            )
            running += tc["effective_input_units"]
            by_turn[turn.turn_index].append(running)
    cum_curve = {t: statistics.mean(vals) for t, vals in sorted(by_turn.items())}
    n_conv = max(1, len(transcripts))
    return {
        "strategy": strategy,
        "aggregate": agg,
        "cost": cost,
        "effective_input_units_per_conv": cost["effective_input_units"] / n_conv,
        "prefix_change_rate": _prefix_change_rate(transcripts),
        "mean_history_tokens": statistics.mean(history_tokens) if history_tokens else 0.0,
        "latency_p50_s": p50,
        "latency_p95_s": p95,
        "cumulative_units_by_turn": cum_curve,
    }


def _save_cost_chart(results: dict[str, dict[str, Any]], path: Path) -> bool:
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return False
    fig, ax = plt.subplots(figsize=(7, 4))
    for arm, data in results.items():
        curve = data["cumulative_units_by_turn"]
        if curve:
            turns = sorted(curve)
            ax.plot(turns, [curve[t] for t in turns], marker="o", label=arm)
    ax.set_xlabel("Turn index")
    ax.set_ylabel("Mean cumulative effective input token units")
    ax.set_title("Cumulative billed input token units by turn")
    ax.legend()
    ax.grid(True, alpha=0.3)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return True


def render_ab_report(
    settings: Settings,
    results: dict[str, dict[str, Any]],
    sweep: list[dict[str, Any]],
    *,
    n_test_scenarios: int,
    n_dev_scenarios: int,
    repeats: int,
    simulator_model: str,
    chart_saved: bool,
    kv_note: str,
    provenance: dict[str, Any],
    rendered_from: str | None = None,
) -> str:
    models = provenance.get("models", {})
    fast_name, main_name = models.get("fast"), models.get("main")

    def _fmt(entry: dict[str, Any], pct: bool = False) -> str:
        mean = entry.get("mean")
        if mean is None:
            return "n/a"
        scale = 100.0 if pct else 1.0
        suf = "%" if pct else ""
        lo, hi = entry["low"] * scale, entry["high"] * scale
        return f"{mean * scale:.2f}{suf} [{lo:.2f}{suf}, {hi:.2f}{suf}]"

    lines = [
        "# Prefix-cache context strategy A/B report",
        "",
        "Generated by `make eval-context-ab`. Do not edit by hand.",
        "",
        f"- Git SHA: `{provenance['git_sha']}` (dirty: {provenance['dirty']})",
        f"- Config hash: `{provenance['config_hash']}`",
        *(
            [f"- Re-rendered without model calls from saved run `{rendered_from}`"]
            if rendered_from
            else []
        ),
        f"- Test scenarios: {n_test_scenarios} x {repeats} repeat(s) per arm",
        f"- Dev scenarios (chunk_turns sweep only): {n_dev_scenarios}",
        f"- Agent models: fast=`{fast_name or 'unset'}`, main=`{main_name or 'unset'}`",
        f"- Simulator model: `{simulator_model}`",
        f"- Cache multipliers: read=`{settings.context.cache_read_multiplier}`, "
        f"write=`{settings.context.cache_write_multiplier}` "
        "(USD prices unset in config, so billed cost is reported in effective input-token units)",
        f"- Run date (UTC): {str(provenance['date'])[:10]}",
        "",
        "## 1. Four-arm comparison (test split, 95% bootstrap CI)",
        "",
        "| Arm | Task success | Fact retention | Redundant Q | Cache hit ratio | "
        "Stable prefix change rate | Mean hist tok | Eff. input units/conv | Latency P50/P95 (s) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm, data in results.items():
        agg = data["aggregate"]
        cost = data["cost"]
        hit_pct = cost["cache_hit_ratio"] * 100
        lines.append(
            f"| `{arm}` | {_fmt(agg['task_success'], True)} | "
            f"{_fmt(agg['fact_retention'], True)} | {_fmt(agg['redundant_questions'])} | "
            f"{hit_pct:.1f}% | {_pct(data['prefix_change_rate'])} | "
            f"{data['mean_history_tokens']:.1f} | "
            f"{data['effective_input_units_per_conv']:.1f} | "
            f"{data['latency_p50_s']:.2f} / {data['latency_p95_s']:.2f} |"
        )

    lines.extend(
        [
            "",
            "`chunked_nocache` sends no cache breakpoints, but the provider caches prompt",
            "prefixes on its own, so its cache hit ratio is observed rather than zero. Its",
            "effective units price every cache read at the full input rate: a counterfactual",
            "for a provider without prefix caching, not a measured run without a cache.",
            "The stable prefix change rate covers L0..L2 only. A sliding window that shifts",
            "L3 history leaves it unchanged; that cost shows up in the cache hit ratio.",
        ]
    )
    lines.extend(
        [
            "",
            "## 2. Cost decomposition (total tokens across all test runs)",
            "",
            "| Arm | Total input | Uncached input | Cache reads | Cache writes | "
            "Output | Effective input units |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for arm, data in results.items():
        c = data["cost"]
        lines.append(
            f"| `{arm}` | {c['total_input_tokens']:.0f} | {c['uncached_input_tokens']:.0f} | "
            f"{c['cache_read_tokens']:.0f} | {c['cache_write_tokens']:.0f} | "
            f"{c['output_tokens']:.0f} | {c['effective_input_units']:.1f} |"
        )

    if chart_saved:
        lines.extend(["", "![Cumulative effective input units by turn](context_ab_cost.png)"])

    lines.extend(
        [
            "",
            "## 3. `chunk_turns` sensitivity sweep (dev split only)",
            "",
            "| `chunk_turns` | Task success | Cache hit ratio | Eff. input units/conv | "
            "Mean hist tok |",
            "|---:|---:|---:|---:|---:|",
        ]
    )
    for row in sweep:
        lines.append(
            f"| {row['chunk_turns']} | {_fmt(row['aggregate']['task_success'], True)} | "
            f"{row['cost']['cache_hit_ratio'] * 100:.1f}% | "
            f"{row['effective_input_units_per_conv']:.1f} | "
            f"{row['mean_history_tokens']:.1f} |"
        )

    # Honest conclusion noting any arm where chunked lost.
    chunked_units = results["chunked"]["effective_input_units_per_conv"]
    losses = [
        f"`{arm}` ({data['effective_input_units_per_conv']:.1f} vs {chunked_units:.1f} units/conv)"
        for arm, data in results.items()
        if arm != "chunked" and data["effective_input_units_per_conv"] < chunked_units
    ]
    lines.extend(
        [
            "",
            "## 4. Conclusion",
            "",
            f"- `chunked` cost `{chunked_units:.1f}` effective input units/conv; priced at "
            "the full input rate (the `chunked_nocache` counterfactual) the same kind of "
            f"run cost `{results['chunked_nocache']['effective_input_units_per_conv']:.1f}`.",
            (
                f"- Arms where `chunked` had higher effective units/conv: {', '.join(losses)}."
                if losses
                else "- `chunked` had the lowest effective input units/conv across all four arms."
            ),
            "",
            "## 5. KV-level view (self-hosted vLLM)",
            "",
            f"- Status: {kv_note}",
            "",
        ]
    )
    return "\n".join(lines)


def _run_arm(
    base_settings: Settings,
    scenarios: list[Scenario],
    *,
    strategy: ContextStrategy,
    simulator: UserSimulator,
    repeats: int,
    chunk_turns: int | None = None,
) -> tuple[dict[str, Any], list[ConversationTranscript]]:
    settings = base_settings.model_copy(deep=True)
    settings.context.strategy = strategy
    if chunk_turns is not None:
        settings.memory.short_term.chunk_turns = chunk_turns
    by_id = {s.id: s for s in scenarios}
    order_service = OrderService(platform=settings)
    graph_deps = GraphDeps(settings=settings, order_service=order_service)
    try:
        transcripts = asyncio.run(
            run_suite(
                settings,
                scenarios,
                simulator=simulator,
                graph_deps=graph_deps,
                order_service=order_service,
                repeats=repeats,
            )
        )
    finally:
        order_service.close()
    evals = [
        evaluate_transcript(
            by_id[tr.scenario_id], tr, loop_threshold=settings.eval.sim.loop_threshold
        )
        for tr in transcripts
    ]
    agg = aggregate_evaluations(
        evals,
        n_resamples=settings.eval.stats.n_resamples,
        seed=settings.eval.sim.seed,
        alpha=settings.eval.stats.alpha,
    )
    return _arm_metrics(strategy, transcripts, agg, settings), transcripts


def main(argv: list[str] | None = None) -> int:
    _dirty_at_start()
    parser = argparse.ArgumentParser(description="Run 4-arm prefix-cache A/B experiment.")
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--test-limit", type=int, default=6)
    parser.add_argument("--dev-limit", type=int, default=3)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--chart", type=Path, default=DEFAULT_CHART)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument(
        "--from-run", type=Path, help="re-render the report from a saved run (no model calls)"
    )
    args = parser.parse_args(argv)
    if args.from_run:
        return rerender(args.from_run, args.report, args.chart)

    base = get_settings().model_copy(deep=True)
    base.api.rate_limit.per_customer = 10000
    base.api.rate_limit.per_ip = 10000
    # Tighter history budget to exercise compaction/sliding across arms evenly.
    base.memory.short_term.history_budget = 600
    base.context.sliding_window_turns = 3

    all_scenarios = load_scenarios(args.scenarios)
    test_scenarios = [s for s in all_scenarios if s.split == "test" and s.nightly][
        : args.test_limit
    ]
    dev_scenarios = [s for s in all_scenarios if s.split == "dev"][: args.dev_limit]

    sim_model, sim_name = build_simulator_model(base)
    simulator = UserSimulator(sim_model, model_name=sim_name, retry=base.eval.sim.retry)

    results: dict[str, dict[str, Any]] = {}
    prompt_records: list[dict[str, Any]] = []
    # Every transcript, so later metric fixes can re-score this run without model calls.
    item_records: list[dict[str, Any]] = []
    arm_transcripts: dict[str, list[ConversationTranscript]] = {}
    for strategy in STRATEGIES:
        metrics, transcripts = _run_arm(
            base, test_scenarios, strategy=strategy, simulator=simulator, repeats=args.repeats
        )
        results[strategy] = metrics
        arm_transcripts[strategy] = transcripts
        item_records.extend(
            {"arm": strategy, "split": "test", "transcript": tr.model_dump(mode="json")}
            for tr in transcripts
        )
        for tr in transcripts:
            for turn in tr.turns:
                prompt_records.append(
                    {
                        "strategy": strategy,
                        "scenario_id": tr.scenario_id,
                        "turn": turn.turn_index,
                        "user_message": turn.user_message,
                    }
                )

    sweep_rows: list[dict[str, Any]] = []
    for chunk_k in (4, 6, 10):
        row, sweep_transcripts = _run_arm(
            base,
            dev_scenarios,
            strategy="chunked",
            simulator=simulator,
            repeats=1,
            chunk_turns=chunk_k,
        )
        row["chunk_turns"] = chunk_k
        arm_transcripts[f"chunked-k{chunk_k}"] = sweep_transcripts
        item_records.extend(
            {"arm": f"chunked-k{chunk_k}", "split": "dev", "transcript": tr.model_dump(mode="json")}
            for tr in sweep_transcripts
        )
        sweep_rows.append(row)

    run_dir = args.run_root / f"context-ab-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=True)
    write_text(
        run_dir / "prompts.jsonl",
        "\n".join(json.dumps(r, ensure_ascii=False) for r in prompt_records) + "\n",
    )
    write_text(
        run_dir / "metrics.json",
        json.dumps({"arms": results, "sweep": sweep_rows}, indent=2) + "\n",
    )
    write_text(
        run_dir / "items.jsonl",
        "\n".join(json.dumps(r, ensure_ascii=False) for r in item_records) + "\n",
    )
    provenance = {
        **run_provenance(base, sim_name),
        "n_test_scenarios": len(test_scenarios),
        "n_dev_scenarios": len(dev_scenarios),
        "repeats": args.repeats,
    }
    write_text(run_dir / "run.json", json.dumps(provenance, indent=2) + "\n")
    if broken := invalid_arms_message(arm_transcripts):
        sys.stderr.write(f"Invalid run, nothing reported: {broken}\nRows kept in {run_dir}\n")
        return INVALID_RUN_STATUS

    chart_saved = _save_cost_chart(results, args.chart)
    kv_note = (
        "skipped: no NVIDIA GPU detected on this host (`make bench-kv` skips cleanly without GPU)."
        if shutil.which("nvidia-smi") is None
        else "GPU available; run `make bench-kv` against vLLM."
    )
    write_text(
        args.report,
        render_ab_report(
            base,
            results,
            sweep_rows,
            n_test_scenarios=len(test_scenarios),
            n_dev_scenarios=len(dev_scenarios),
            repeats=args.repeats,
            simulator_model=sim_name,
            chart_saved=chart_saved,
            kv_note=kv_note,
            provenance=provenance,
        ),
    )
    return 0


def rerender(run_dir: Path, report: Path, chart: Path) -> int:
    """Render the report again from a saved run, keeping that run's provenance."""
    provenance = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    rows = [
        json.loads(line)
        for line in (run_dir / "items.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    test = [r for r in rows if r["split"] == "test"]
    counts = {
        "n_test_scenarios": len({r["transcript"]["scenario_id"] for r in test}),
        "n_dev_scenarios": len(
            {r["transcript"]["scenario_id"] for r in rows if r["split"] == "dev"}
        ),
        "repeats": 1 + max((r["transcript"].get("repeat_index", 0) for r in test), default=0),
    }
    counts.update({k: provenance[k] for k in counts if k in provenance})
    chart_saved = _save_cost_chart(metrics["arms"], chart)
    kv_note = (
        "skipped: no NVIDIA GPU detected on this host (`make bench-kv` skips cleanly without GPU)."
        if shutil.which("nvidia-smi") is None
        else "GPU available; run `make bench-kv` against vLLM."
    )
    write_text(
        report,
        render_ab_report(
            get_settings(),
            metrics["arms"],
            metrics["sweep"],
            simulator_model=str(provenance.get("simulator_model", "unknown")),
            chart_saved=chart_saved,
            kv_note=kv_note,
            provenance=provenance,
            rendered_from=run_dir.name,
            **counts,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
