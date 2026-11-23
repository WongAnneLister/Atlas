"""Drive multi-turn simulated conversations through the Atlas ASGI API."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import httpx
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from prometheus_client import CollectorRegistry

from eval.registry import file_hash, load_registry
from eval.sim.build_scenarios import DEFAULT_OUTPUT as DEFAULT_SCENARIOS
from eval.sim.build_scenarios import load_scenarios
from eval.sim.metrics import aggregate_evaluations, evaluate_transcript
from eval.sim.models import ConversationTranscript, Scenario, SimTurn, ToolCallRecord
from eval.sim.report import render_sim_report, render_validity_template
from eval.sim.user import UserSimulator, build_simulator_model
from support_agent.api.app import create_app
from support_agent.api.deps import ApiDeps
from support_agent.api.readiness import ReadinessChecks
from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.data.doc_models import write_text
from support_agent.graph.deps import GraphDeps
from support_agent.infra.redis import NullRedis
from support_agent.orders.service import OrderService

DEFAULT_REPORT = REPO_ROOT / "eval" / "reports" / "sim.md"
DEFAULT_VALIDITY = REPO_ROOT / "eval" / "reports" / "sim_validity.md"
DEFAULT_RUN_ROOT = REPO_ROOT / "eval" / "runs"


def parse_sse(body: str) -> list[tuple[str, Any]]:
    """Parse an SSE response payload into (event_name, parsed_data) tuples."""
    events: list[tuple[str, Any]] = []
    event_name = "message"
    data_lines: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip("\r")
        if not line:
            if data_lines:
                raw_data = "\n".join(data_lines)
                try:
                    parsed: Any = json.loads(raw_data)
                except json.JSONDecodeError:
                    parsed = raw_data
                events.append((event_name, parsed))
                event_name = "message"
                data_lines = []
            continue
        if line.startswith("event:"):
            event_name = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
    if data_lines:
        raw_data = "\n".join(data_lines)
        try:
            parsed = json.loads(raw_data)
        except json.JSONDecodeError:
            parsed = raw_data
        events.append((event_name, parsed))
    return events


def _extract_turn_sse(events: list[tuple[str, Any]]) -> dict[str, Any]:
    tokens: list[str] = []
    citations: list[dict[str, Any]] = []
    handoff_reason: str | None = None
    handoff_message: str | None = None
    interrupt_payload: Any = None
    error_type: str | None = None
    for name, data in events:
        if name == "token" and isinstance(data, dict):
            tokens.append(str(data.get("text", "")))
        elif name == "citations" and isinstance(data, list):
            citations = [item for item in data if isinstance(item, dict)]
        elif name == "handoff" and isinstance(data, dict):
            handoff_reason = str(data.get("reason", "")) or None
            handoff_message = str(data.get("message", "")) or None
        elif name == "interrupt":
            interrupt_payload = data
        elif name == "error":
            error_type = (
                str(data.get("code") or data.get("message") or "sse_error")
                if isinstance(data, dict)
                else "sse_error"
            )
    answer = "".join(tokens).strip()
    if not answer and handoff_message:
        answer = handoff_message
    elif handoff_message and handoff_message not in answer:
        answer = f"{answer}\n\n{handoff_message}".strip()
    return {
        "answer": answer,
        "citations": citations,
        "handoff_reason": handoff_reason,
        "interrupt": interrupt_payload,
        "error_type": error_type,
    }


def _read_checkpoint_diagnostics(
    graph_deps: GraphDeps, thread_id: str, prev_msg_count: int
) -> tuple[list[str], list[ToolCallRecord], str | None, int, int, int]:
    """Read internal trace, tool calls, refund id, and token usage from the checkpointer."""
    saver = graph_deps.checkpointer()
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    saved = saver.get_tuple(config)
    if saved is None:
        return [], [], None, 0, 0, prev_msg_count
    values: dict[str, Any] = saved.checkpoint.get("channel_values", {})
    route = list(values.get("trace", []))
    messages = list(values.get("messages", []))
    new_messages = messages[prev_msg_count:]
    tool_calls: list[ToolCallRecord] = []
    in_tok = 0
    out_tok = 0
    for msg in new_messages:
        if isinstance(msg, AIMessage):
            for call in getattr(msg, "tool_calls", None) or []:
                if isinstance(call, dict):
                    tool_calls.append(
                        ToolCallRecord(
                            name=str(call.get("name", "")),
                            args=dict(call.get("args", {}) or {}),
                        )
                    )
            usage = msg.usage_metadata or msg.response_metadata.get("token_usage")
            if isinstance(usage, dict):
                in_tok += int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
                out_tok += int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
    refund = values.get("refund_request")
    refund_id = None
    if isinstance(refund, dict) and refund.get("request_id"):
        refund_id = str(refund["request_id"])
    return route, tool_calls, refund_id, in_tok, out_tok, len(messages)


async def run_scenario_over_api(
    client: httpx.AsyncClient,
    graph_deps: GraphDeps,
    simulator: UserSimulator,
    scenario: Scenario,
    *,
    repeat_index: int = 0,
) -> ConversationTranscript:
    """Run one multi-turn conversation through /api/session, /api/chat, and /api/resume."""
    session_resp = await client.post("/api/session", json={"customer_id": scenario.customer_id})
    if session_resp.status_code != 200:
        return ConversationTranscript(
            scenario_id=scenario.id,
            category=scenario.category,
            customer_id=scenario.customer_id,
            repeat_index=repeat_index,
            stop_reason="error",
            simulator_model=simulator.model_name,
        )
    token = session_resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    conv_id = f"sim-{uuid4().hex[:12]}"
    thread_id = f"{scenario.customer_id}:{conv_id}"

    visible_history: list[tuple[Literal["user", "assistant"], str]] = []
    turns: list[SimTurn] = []
    stop_reason: Literal["done", "max_turns", "handoff", "error"] = "max_turns"
    prev_msg_count = 0

    for turn_idx in range(1, scenario.max_turns + 1):
        sim_reply = simulator.next_turn(scenario, visible_history, turn_idx)
        if not sim_reply.text and sim_reply.done:
            stop_reason = "done"
            break
        user_text = sim_reply.text or "Thanks, that is all."
        visible_history.append(("user", user_text))

        started = time.perf_counter()
        resp = await client.post(
            "/api/chat",
            headers=headers,
            json={"conversation_id": conv_id, "message": user_text},
        )
        elapsed = time.perf_counter() - started
        if resp.status_code != 200:
            turns.append(
                SimTurn(
                    turn_index=turn_idx,
                    user_message=user_text,
                    latency_s=elapsed,
                    error_type=f"http_{resp.status_code}",
                )
            )
            stop_reason = "error"
            break

        parsed = _extract_turn_sse(parse_sse(resp.text))
        interrupt_prompt: str | None = None
        resume_choice: str | None = None

        if parsed["interrupt"] is not None:
            interrupt_data = parsed["interrupt"]
            candidates = (
                interrupt_data.get("orders", []) if isinstance(interrupt_data, dict) else []
            )
            interrupt_prompt = (
                str(interrupt_data.get("prompt", "Please choose an order."))
                if isinstance(interrupt_data, dict)
                else str(interrupt_data)
            )
            resume_choice = simulator.choose_order(scenario, candidates)
            resume_start = time.perf_counter()
            resume_resp = await client.post(
                "/api/resume",
                headers=headers,
                json={"conversation_id": conv_id, "value": resume_choice},
            )
            elapsed += time.perf_counter() - resume_start
            if resume_resp.status_code != 200:
                turns.append(
                    SimTurn(
                        turn_index=turn_idx,
                        user_message=user_text,
                        interrupt_prompt=interrupt_prompt,
                        resume_choice=resume_choice,
                        latency_s=elapsed,
                        error_type=f"resume_http_{resume_resp.status_code}",
                    )
                )
                stop_reason = "error"
                break
            parsed = _extract_turn_sse(parse_sse(resume_resp.text))

        route, tool_calls, refund_id, in_tok, out_tok, prev_msg_count = (
            _read_checkpoint_diagnostics(graph_deps, thread_id, prev_msg_count)
        )
        agent_text = parsed["answer"]
        visible_history.append(("assistant", agent_text))
        turns.append(
            SimTurn(
                turn_index=turn_idx,
                user_message=user_text,
                agent_message=agent_text,
                interrupt_prompt=interrupt_prompt,
                resume_choice=resume_choice,
                route=route,
                tool_calls=tool_calls,
                handoff_reason=parsed["handoff_reason"],
                citations=parsed["citations"],
                refund_request_id=refund_id,
                input_tokens=in_tok,
                output_tokens=out_tok,
                latency_s=elapsed,
                error_type=parsed["error_type"],
            )
        )
        if parsed["error_type"] is not None:
            stop_reason = "error"
            break
        if sim_reply.done:
            stop_reason = "done"
            break
        if parsed["handoff_reason"] is not None:
            stop_reason = "handoff"
            break

    return ConversationTranscript(
        scenario_id=scenario.id,
        category=scenario.category,
        customer_id=scenario.customer_id,
        repeat_index=repeat_index,
        turns=turns,
        stop_reason=stop_reason,
        simulator_model=simulator.model_name,
    )


async def run_suite(
    settings: Settings,
    scenarios: list[Scenario],
    *,
    simulator: UserSimulator,
    graph_deps: GraphDeps,
    order_service: OrderService,
    repeats: int = 1,
) -> list[ConversationTranscript]:
    """Spin up an in-process ASGI app and run all scenarios x repeats."""
    store = NullRedis()
    api_deps = ApiDeps(
        settings=settings,
        graph_deps=graph_deps,
        order_service=order_service,
        milvus_check=lambda: True,
        warmup=False,
        readiness=ReadinessChecks(),
        lock_store=store,
        metrics_registry=CollectorRegistry(),
    )
    app = create_app(api_deps)
    transcripts: list[ConversationTranscript] = []
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://atlas.local") as client:
            for scenario in scenarios:
                for repeat_idx in range(repeats):
                    transcript = await run_scenario_over_api(
                        client, graph_deps, simulator, scenario, repeat_index=repeat_idx
                    )
                    transcripts.append(transcript)
    return transcripts


def _select_scenarios(
    scenarios: list[Scenario], *, split: str, subset: str, limit: int | None
) -> list[Scenario]:
    chosen = [s for s in scenarios if split == "all" or s.split == split]
    if subset == "nightly":
        chosen = [s for s in chosen if s.nightly]
    if limit is not None:
        chosen = chosen[:limit]
    if not chosen:
        raise ValueError("No scenarios matched the requested split/subset")
    return chosen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run multi-turn simulated support evaluations.")
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    parser.add_argument("--split", choices=["dev", "test", "all"], default="test")
    parser.add_argument("--subset", choices=["all", "nightly"], default="all")
    parser.add_argument("--repeats", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--validity-report", type=Path, default=DEFAULT_VALIDITY)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    args = parser.parse_args(argv)

    settings = get_settings().model_copy(deep=True)
    # Allow high request volume during local/ASGI simulation runs.
    settings.api.rate_limit.per_customer = 10000
    settings.api.rate_limit.per_ip = 10000

    entry = load_registry().get("scenarios_v1")
    dataset_version = entry.version if entry is not None else "v1"
    if (
        entry is not None
        and args.scenarios.resolve() == (REPO_ROOT / entry.path).resolve()
        and file_hash(args.scenarios) != entry.sha256
    ):
        raise ValueError("scenarios_v1.jsonl hash does not match eval/registry.yaml")

    scenarios = _select_scenarios(
        load_scenarios(args.scenarios), split=args.split, subset=args.subset, limit=args.limit
    )
    repeats = args.repeats if args.repeats is not None else settings.eval.sim.repeats
    sim_model, sim_name = build_simulator_model(settings)
    simulator = UserSimulator(sim_model, model_name=sim_name)

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

    by_id = {s.id: s for s in scenarios}
    evaluations = [
        evaluate_transcript(
            by_id[tr.scenario_id],
            tr,
            loop_threshold=settings.eval.sim.loop_threshold,
        )
        for tr in transcripts
    ]
    agg = aggregate_evaluations(
        evaluations,
        n_resamples=settings.eval.stats.n_resamples,
        seed=settings.eval.sim.seed,
        alpha=settings.eval.stats.alpha,
    )

    run_dir = args.run_root / f"sim-{args.split}-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=True)
    write_text(
        run_dir / "items.jsonl",
        "\n".join(tr.model_dump_json() for tr in transcripts) + "\n",
    )
    write_text(run_dir / "metrics.json", json.dumps(agg, indent=2) + "\n")

    write_text(
        args.report,
        render_sim_report(
            settings,
            agg,
            dataset_version=dataset_version,
            split=args.split,
            subset=args.subset,
            repeats=repeats,
            simulator_model=sim_name,
        ),
    )
    write_text(
        args.validity_report,
        render_validity_template(
            transcripts,
            sample_size=settings.eval.sim.validity_sample_size,
            run_dir=run_dir,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
