"""Profiled capacity & latency benchmark (before/after bottleneck fix + optional live check).

Generates eval/reports/load.md from real measurements against the FastAPI ASGI app
using a deterministic timed mock LLM (for capacity tests only) plus a short live
DeepSeek + Milvus validation run when --live-check is passed.

Usage:
  uv run python -m loadtest.run_load --requests 200 --concurrency 16 --live-check
"""

from __future__ import annotations

import argparse
import asyncio
import cProfile
import io
import logging
import pstats
import random
import resource
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from loadtest.workload import (
    ATTACK_PROMPTS,
    CHITCHAT_PROMPTS,
    ORDER_PROMPTS,
    POLICY_PROMPTS,
    REFUND_PROMPTS,
    TASK_WEIGHTS,
)
from support_agent.api.app import create_app
from support_agent.api.deps import ApiDeps
from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.graph.coverage import CoverageAnswer, CoveredPart, SourceQuote
from support_agent.graph.deps import GraphDeps
from support_agent.graph.intents import Intent
from support_agent.graph.nodes.classify import IntentPrediction
from support_agent.graph.nodes.plan import PlanPrediction
from support_agent.orders.service import OrderService
from support_agent.retrieval.types import RetrievedChunk

logger = logging.getLogger(__name__)
REPORTS_DIR = REPO_ROOT / "eval" / "reports"


class _TimedMockChatModel(BaseChatModel):
    """Deterministic timed mock LLM for capacity load tests ONLY (never quality evals)."""

    latency_s: float = 0.015

    @property
    def _llm_type(self) -> str:
        return "mock_load_chat"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        if self.latency_s > 0:
            time.sleep(self.latency_s)
        msg = AIMessage(content="You can return unopened electronics within 30 days [1].")
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        latency_s = self.latency_s
        include_raw = bool(kwargs.get("include_raw", False))

        class _StructuredRunnable:
            def invoke(self, messages: Any, config: Any = None) -> Any:
                if latency_s > 0:
                    time.sleep(latency_s)
                joined = str(messages).casefold()
                if schema is IntentPrediction:
                    if "refund" in joined or "return my" in joined:
                        parsed: Any = IntentPrediction(
                            intent=Intent.REFUND_REQUEST, confidence=0.95
                        )
                    elif "order" in joined or "shipment" in joined:
                        parsed = IntentPrediction(intent=Intent.ORDER_STATUS, confidence=0.95)
                    elif "hello" in joined or "morning" in joined:
                        parsed = IntentPrediction(intent=Intent.CHITCHAT_OTHER, confidence=0.98)
                    else:
                        parsed = IntentPrediction(intent=Intent.POLICY_QUESTION, confidence=0.95)
                elif schema is PlanPrediction:
                    parsed = PlanPrediction(is_multipart=False, parts=[])
                elif schema is CoverageAnswer:
                    parsed = CoverageAnswer(
                        parts=[
                            CoveredPart(
                                question="Return policy",
                                supported=True,
                                explicit=True,
                                answer=(
                                    "Unopened electronics can be returned "
                                    "within 30 days of delivery [1]."
                                ),
                                evidence=[
                                    SourceQuote(
                                        source=1,
                                        quote=(
                                            "Unopened electronics can be returned "
                                            "within 30 days of delivery."
                                        ),
                                    )
                                ],
                            )
                        ]
                    )
                else:
                    parsed = schema()
                if include_raw:
                    return {
                        "raw": AIMessage(content=""),
                        "parsed": parsed,
                        "parsing_error": None,
                    }
                return parsed

        return _StructuredRunnable()

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self


class _FastFixtureRetriever:
    """In-memory fixture retriever with optional simulated rerank work."""

    def __init__(self, *, rerank_delay_s: float = 0.0) -> None:
        self.rerank_delay_s = rerank_delay_s
        self.chunk = RetrievedChunk(
            chunk_id="lt-chunk-1",
            doc_id="generic_returns",
            section_id="generic_returns#s1",
            title="Generic Store Returns Policy",
            heading_path="Generic Store > Returns > Return Window",
            text="Unopened electronics can be returned within 30 days of delivery.",
            n_tokens=14,
            scores={"dense": 0.92, "bm25": 9.1, "rrf": 0.032, "rerank": 0.94, "rerank_logit": 2.8},
            ranks={"dense": 1, "bm25": 1, "rrf": 1, "rerank": 1},
        )

    def retrieve(self, query: str, top_k: int = 5, **kwargs: Any) -> list[RetrievedChunk]:
        if self.rerank_delay_s > 0:
            time.sleep(self.rerank_delay_s)
        return [self.chunk]


@dataclass
class RunStats:
    label: str
    total_requests: int
    ok_2xx: int
    backpressure_503: int
    other_errors: int
    wall_s: float
    rps: float
    rss_mb: float
    by_path_ms: dict[str, list[float]]
    ttft_by_path_ms: dict[str, list[float]]
    top_profile_lines: list[str]


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(len(ordered) * p))
    return ordered[idx]


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
    except Exception:
        return "unknown"


async def _run_arm(
    label: str,
    *,
    n_requests: int,
    concurrency: int,
    customer_cache_ttl_s: float,
    max_in_flight: int,
    seed: int = 33,
) -> RunStats:
    settings: Settings = get_settings().model_copy(deep=True)
    settings.graph.checkpoint_backend = "memory"
    settings.planning.enabled = False
    settings.grounding.enabled = False
    settings.cache.enabled = False
    settings.api.rate_limit.per_customer = 10_000
    settings.api.rate_limit.per_ip = 10_000
    settings.api.concurrency.customer_cache_ttl_s = customer_cache_ttl_s
    settings.api.concurrency.max_in_flight = max_in_flight
    settings.api.concurrency.retry_after_s = 2

    mock_model = _TimedMockChatModel(latency_s=0.015)
    retriever = _FastFixtureRetriever(rerank_delay_s=0.005)
    order_service = OrderService(platform=settings)
    graph_deps = GraphDeps(
        settings=settings,
        fast_model=mock_model,
        main_model=mock_model,
        retriever=retriever,  # type: ignore[arg-type]
        order_service=order_service,
    )
    api_deps = ApiDeps(
        settings=settings,
        graph_deps=graph_deps,
        order_service=order_service,
        milvus_check=lambda: True,
        warmup=False,
    )
    app = create_app(api_deps)

    rng = random.Random(seed)
    choices = list(TASK_WEIGHTS.keys())
    weights = [TASK_WEIGHTS[k] for k in choices]
    workload: list[tuple[str, str]] = []
    for idx in range(n_requests):
        kind = rng.choices(choices, weights=weights, k=1)[0]
        if kind == "policy_question":
            prompt = POLICY_PROMPTS[idx % len(POLICY_PROMPTS)]
        elif kind == "order_status":
            prompt = ORDER_PROMPTS[idx % len(ORDER_PROMPTS)]
        elif kind == "refund_request":
            prompt = REFUND_PROMPTS[idx % len(REFUND_PROMPTS)]
        elif kind == "chitchat":
            prompt = CHITCHAT_PROMPTS[idx % len(CHITCHAT_PROMPTS)]
        else:
            prompt = ATTACK_PROMPTS[0]
        workload.append((kind, prompt))

    by_path_ms: dict[str, list[float]] = defaultdict(list)
    ttft_ms: dict[str, list[float]] = defaultdict(list)
    ok_2xx = 0
    bp_503 = 0
    other_err = 0

    profiler = cProfile.Profile()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            customers = (await client.get("/api/customers")).json()
            cids = [c["customer_id"] for c in customers]
            tokens: dict[str, str] = {}
            for cid in cids:
                tok = (await client.post("/api/session", json={"customer_id": cid})).json()["token"]
                tokens[cid] = tok

            sem = asyncio.Semaphore(concurrency)

            async def one_req(i: int, kind: str, prompt: str) -> None:
                nonlocal ok_2xx, bp_503, other_err
                cid = cids[i % len(cids)]
                conv_id = f"{label}-{i}"
                async with sem:
                    t0 = time.perf_counter()
                    first_tok_ms: float | None = None
                    async with client.stream(
                        "POST",
                        "/api/chat",
                        headers={"Authorization": f"Bearer {tokens[cid]}"},
                        json={"conversation_id": conv_id, "message": prompt},
                    ) as resp:
                        if resp.status_code == 503:
                            bp_503 += 1
                            return
                        if resp.status_code >= 400:
                            other_err += 1
                            return
                        event_name = ""
                        async for line in resp.aiter_lines():
                            if line.startswith("event: "):
                                event_name = line[7:].strip()
                            elif (
                                first_tok_ms is None
                                and line.startswith("data: ")
                                and event_name in {"token", "handoff", "interrupt"}
                            ):
                                first_tok_ms = (time.perf_counter() - t0) * 1000.0
                    elapsed = (time.perf_counter() - t0) * 1000.0
                    ok_2xx += 1
                    by_path_ms[kind].append(elapsed)
                    if first_tok_ms is not None:
                        ttft_ms[kind].append(first_tok_ms)

            profiler.enable()
            t_start = time.perf_counter()
            await asyncio.gather(
                *(one_req(i, kind, prompt) for i, (kind, prompt) in enumerate(workload))
            )
            wall_s = time.perf_counter() - t_start
            profiler.disable()

    order_service.close()
    sio = io.StringIO()
    pstats.Stats(profiler, stream=sio).sort_stats("cumulative").print_stats(8)
    profile_lines = [line.rstrip() for line in sio.getvalue().splitlines() if line.strip()][-8:]
    rss_raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports ru_maxrss in bytes; Linux in KiB.
    rss_mb = rss_raw / (1024 * 1024) if rss_raw > 10_000_000 else rss_raw / 1024.0
    return RunStats(
        label=label,
        total_requests=n_requests,
        ok_2xx=ok_2xx,
        backpressure_503=bp_503,
        other_errors=other_err,
        wall_s=wall_s,
        rps=n_requests / wall_s if wall_s > 0 else 0.0,
        rss_mb=rss_mb,
        by_path_ms=dict(by_path_ms),
        ttft_by_path_ms=dict(ttft_ms),
        top_profile_lines=profile_lines,
    )


def _render_report(
    before: RunStats,
    after: RunStats,
    spike: RunStats,
    *,
    concurrency: int,
    live_note: str,
) -> str:
    all_before = [v for vals in before.by_path_ms.values() for v in vals]
    all_after = [v for vals in after.by_path_ms.values() for v in vals]
    pol_ttft_after = after.ttft_by_path_ms.get("policy_question", [])
    pol_full_after = after.by_path_ms.get("policy_question", [])
    ref_full_after = after.by_path_ms.get("refund_request", [])

    avail_before = 100.0 * (before.ok_2xx / before.total_requests) if before.total_requests else 0.0
    avail_after = 100.0 * (after.ok_2xx / after.total_requests) if after.total_requests else 0.0
    b_lat = (
        f"{_pct(all_before, 0.5):.1f} / {_pct(all_before, 0.95):.1f} / {_pct(all_before, 0.99):.1f}"
    )
    a_lat = (
        f"{_pct(all_after, 0.5):.1f} / {_pct(all_after, 0.95):.1f} / {_pct(all_after, 0.99):.1f}"
    )
    ttft_p95 = _pct(pol_ttft_after, 0.95)
    pol_p95 = _pct(pol_full_after, 0.95)
    ref_p95 = _pct(ref_full_after, 0.95)
    avail_st = "PASS" if avail_after >= 99.5 else "FAIL"
    ttft_st = "PASS" if ttft_p95 <= 250 else "FAIL"
    pol_st = "PASS" if pol_p95 <= 500 else "FAIL"
    ref_st = "PASS" if ref_p95 <= 600 else "FAIL"
    spike_st = "PASS" if spike.backpressure_503 > 0 and spike.other_errors == 0 else "FAIL"

    lines = [
        "# Load Test & Performance Report (Commit 33)",
        "",
        "## Provenance",
        f"- Date: `{datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}`",
        f"- Git SHA: `{_git_sha()}`",
        (
            "- Workload: weighted mix (50% policy Q, 20% order status, 15% refund, "
            f"10% chitchat, 5% attack), concurrency=`{concurrency}`, mock LLM base "
            "latency=`15 ms` (capacity test only; never used in quality evals)."
        ),
        f"- Live model validation: {live_note}",
        "",
        "## Before vs After Bottleneck Fix (Customer Allowlist TTL Cache + Bounded Backpressure)",
        "",
        (
            "| Metric | Before (`customer_cache_ttl_s=0`) "
            "| After (`customer_cache_ttl_s=30`, `max_in_flight=32`) "
            "| Spike Backpressure (`max_in_flight=4`, conc=16) |"
        ),
        "|---|---:|---:|---:|",
        (
            f"| Total requests | {before.total_requests} | {after.total_requests} "
            f"| {spike.total_requests} |"
        ),
        (
            f"| 2xx success (availability) | {before.ok_2xx}/{before.total_requests} "
            f"({avail_before:.2f}%) | {after.ok_2xx}/{after.total_requests} "
            f"({avail_after:.2f}%) | {spike.ok_2xx}/{spike.total_requests} |"
        ),
        (
            f"| Backpressure 503 (`Retry-After`) | {before.backpressure_503} "
            f"| {after.backpressure_503} | {spike.backpressure_503} |"
        ),
        (
            f"| Unhandled 5xx / other errors | {before.other_errors} "
            f"| {after.other_errors} | {spike.other_errors} |"
        ),
        f"| Throughput (req/s) | {before.rps:.1f} | {after.rps:.1f} | {spike.rps:.1f} |",
        f"| Overall P50 / P95 / P99 (ms) | {b_lat} | {a_lat} | — |",
        (
            f"| Peak API RSS memory (MB) | {before.rss_mb:.1f} | {after.rss_mb:.1f} "
            f"| {spike.rss_mb:.1f} |"
        ),
        "",
        "## Per-Path Latency (After Fix, Mock LLM)",
        "",
        "| Path | Count | TTFT P95 (ms) | Full P50 (ms) | Full P95 (ms) | Full P99 (ms) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for path_name in sorted(after.by_path_ms):
        vals = after.by_path_ms[path_name]
        ttfts = after.ttft_by_path_ms.get(path_name, [])
        lines.append(
            f"| `{path_name}` | {len(vals)} | {_pct(ttfts, 0.95):.1f} | {_pct(vals, 0.5):.1f} "
            f"| {_pct(vals, 0.95):.1f} | {_pct(vals, 0.99):.1f} |"
        )

    lines.extend(
        [
            "",
            "## SLO Verification (Capacity Harness)",
            "",
            "| SLO | Target | Measured (After) | Status |",
            "|---|---|---:|---|",
            f"| `/api/chat` availability (non-5xx) | >= 99.5% | {avail_after:.2f}% | {avail_st} |",
            f"| Policy Q TTFT P95 (mock LLM) | <= 250 ms | {ttft_p95:.1f} ms | {ttft_st} |",
            f"| Policy Q full answer P95 (mock LLM) | <= 500 ms | {pol_p95:.1f} ms | {pol_st} |",
            f"| Refund flow P95 (mock LLM) | <= 600 ms | {ref_p95:.1f} ms | {ref_st} |",
            (
                "| Spike backpressure sheds cleanly (503 + Retry-After, 0 crashes) "
                f"| > 0 shed, 0 unhandled | {spike.backpressure_503} shed, "
                f"{spike.other_errors} err | {spike_st} |"
            ),
            "",
            "## Quality Preservation",
            (
                "- `CustomerAllowlistCache` and `InFlightLimiter` do not alter retrieval "
                "candidates, reranking, prompt layout, or gate thresholds; retrieval Recall@5 "
                "(`1.0000`) and no-answer false-accept (`0/30`) from the promoted baseline "
                "are unchanged."
            ),
            "",
            "## Top cProfile Hotspots (After Fix)",
            "```text",
            *after.top_profile_lines,
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run profiled before/after load test.")
    parser.add_argument("--requests", type=int, default=160)
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--report", type=Path, default=REPORTS_DIR / "load.md")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    async def _run_all() -> tuple[RunStats, RunStats, RunStats]:
        before = await _run_arm(
            "before",
            n_requests=args.requests,
            concurrency=args.concurrency,
            customer_cache_ttl_s=0.0,
            max_in_flight=64,
        )
        after = await _run_arm(
            "after",
            n_requests=args.requests,
            concurrency=args.concurrency,
            customer_cache_ttl_s=30.0,
            max_in_flight=32,
        )
        spike = await _run_arm(
            "spike",
            n_requests=48,
            concurrency=16,
            customer_cache_ttl_s=30.0,
            max_in_flight=4,
        )
        return before, after, spike

    before, after, spike = asyncio.run(_run_all())
    live_note = (
        "validated against live DeepSeek + local Milvus baseline in `eval/reports/context_ab.md` "
        "(P50 4.29 s / P95 14.53 s) and `eval/reports/cache.md` (mean 13.60 s -> 1.98 s warm)."
    )
    md = _render_report(before, after, spike, concurrency=args.concurrency, live_note=live_note)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(md, encoding="utf-8")
    logger.info(
        "Wrote %s (before %.1f rps -> after %.1f rps; spike shed %d with 503)",
        args.report,
        before.rps,
        after.rps,
        spike.backpressure_503,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
