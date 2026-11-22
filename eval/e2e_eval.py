"""Run the full graph over a frozen split and write resumable JSONL records."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from eval.common import load_items
from eval.e2e_endpoint import endpoint_host
from eval.e2e_records import E2EMetadata, E2EPart, E2ERecord, load_cached_run
from eval.e2e_report import render_e2e
from eval.e2e_runs import prepare_e2e
from eval.e2e_speed import (
    SpeedOptions,
    add_speed_arguments,
    merge_rerank_scores,
    rerank_scores,
    run_config_hash,
    run_items,
    speed_options,
)
from eval.intent_eval import runtime_versions, source_hash
from eval.metrics import accepted
from eval.run_record import (
    RUNS,
    Run,
    dataset_version,
    is_dirty,
    read_run,
    write_run,
)
from eval.thread_ids import EvalThreads
from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.data.doc_models import digest, write_text
from support_agent.graph.build import build_graph
from support_agent.graph.deps import GraphDeps
from support_agent.graph.parts import QueryPart
from support_agent.llm import Role, resolve_model
from support_agent.observability import tracing
from support_agent.observability.cost import UsageLedger, cost_usd
from support_agent.retrieval.milvus_store import configured_build_id

RunRenderer = Callable[[Run, Path], int | None]


def _git_sha() -> str:
    return subprocess.check_output(
        ["git", "-c", f"safe.directory={REPO_ROOT}", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        text=True,
    ).strip()


def _model_names(settings: Settings) -> dict[str, str]:
    names = {}
    roles: tuple[Role, ...] = ("fast", "main")
    for role in roles:
        primary, _ = resolve_model(role, settings.llm)
        names[role] = primary or "unset"
        fallbacks = list(dict.fromkeys(getattr(settings.llm.fallbacks, role)))
        if primary in fallbacks:
            fallbacks.remove(primary)
        names.update(
            (f"{role}_fallback_{position}", name)
            for position, name in enumerate(fallbacks, start=1)
        )
    return names


def _usage(messages: list[Any]) -> tuple[int | None, int | None]:
    input_tokens = 0
    output_tokens = 0
    found = False
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        usage = message.usage_metadata or message.response_metadata.get("token_usage")
        if not isinstance(usage, dict):
            continue
        input_value = usage.get("input_tokens", usage.get("prompt_tokens"))
        output_value = usage.get("output_tokens", usage.get("completion_tokens"))
        if isinstance(input_value, int) and isinstance(output_value, int):
            input_tokens += input_value
            output_tokens += output_value
            found = True
    return (input_tokens, output_tokens) if found else (None, None)


def _handoff_reason(value: Any) -> str | None:
    reason = getattr(value, "reason", None)
    if reason is None and isinstance(value, dict):
        reason = value.get("reason")
    return getattr(reason, "value", reason) if reason is not None else None


def _run_item(
    graph: Any, item: Any, customer_id: str, thread_id: str, trace: tracing.TurnTrace
) -> tuple[dict[str, Any], float, UsageLedger]:
    usage = UsageLedger()
    config: dict[str, Any] = {
        "configurable": {"thread_id": thread_id},
        "callbacks": [usage, *trace.callbacks],
        "metadata": trace.config_metadata,
    }
    try:
        result = graph.invoke(
            {"messages": [HumanMessage(content=item.question)], "customer_id": customer_id},
            config,
        )
        while result.get("__interrupt__"):
            result = graph.invoke(Command(resume="none"), config)
    except Exception as error:
        trace.finish(None, error_type=type(error).__name__)
        raise
    trace.finish(result)
    return result, time.perf_counter() - usage.started, usage


def _observed_parts(result: dict[str, Any]) -> list[E2EPart] | None:
    if result.get("route_source") == "whole" or not result.get("parts"):
        return None
    observations = []
    for value in result["parts"]:
        if not isinstance(value, QueryPart):
            observations.append(E2EPart.model_validate(value))
            continue
        chunks = value.retrieval[:5]
        observations.append(
            E2EPart(
                text=value.text,
                intent=value.intent.value if value.intent else None,
                gate=value.gate.model_dump() if value.gate else None,
                retrieved_section_ids=[chunk.section_id for chunk in chunks],
                retrieved_sources=[
                    {
                        "section_id": chunk.section_id,
                        "heading_path": chunk.heading_path,
                        "text": chunk.text,
                    }
                    for chunk in chunks
                ],
                answered=value.answered,
                handed_off=value.handed_off,
                cited_section_ids=value.cited_section_ids,
            )
        )
    return observations


def _record(
    item: Any,
    result: dict[str, Any],
    latency: float,
    first_token_latency: float | None,
    token_usage: tuple[int | None, int | None],
    usage: UsageLedger | None = None,
) -> E2ERecord:
    retrieval = result.get("retrieval", [])
    citations = result.get("citations", [])
    cited_sources = []
    for citation in citations:
        number = citation.get("n") if isinstance(citation, dict) else getattr(citation, "n", None)
        if isinstance(number, int) and 1 <= number <= len(retrieval):
            chunk = retrieval[number - 1]
            cited_sources.append(
                {
                    "section_id": chunk.section_id,
                    "heading_path": chunk.heading_path,
                    "text": chunk.text,
                }
            )
    input_tokens, output_tokens = token_usage
    if input_tokens is None or output_tokens is None:
        input_tokens, output_tokens = _usage(result.get("messages", []))
    handoff = result.get("handoff")
    return E2ERecord(
        build_id=result.get("retrieval_build_id"),
        item=item,
        intent=getattr(result.get("intent"), "value", result.get("intent")),
        path=getattr(result.get("path"), "value", result.get("path")),
        trace=list(result.get("trace", [])),
        classification_failed=result.get("classification_failed"),
        classification_error_type=result.get("classification_error_type"),
        retrieval_error_type=result.get("retrieval_error_type"),
        answer_status=result.get("answer_status"),
        answer_error_type=result.get("answer_error_type"),
        route_source=result.get("route_source"),
        claims=[
            claim.model_dump() if hasattr(claim, "model_dump") else claim
            for claim in result["claims"]
        ]
        if result.get("claims") is not None
        else None,
        parts=_observed_parts(result),
        coverage=result["coverage"].model_dump()
        if hasattr(result.get("coverage"), "model_dump")
        else result.get("coverage"),
        gate=result["gate"].model_dump()
        if hasattr(result.get("gate"), "model_dump")
        else result.get("gate"),
        answer=str(result.get("answer", "")),
        citations=[
            citation.model_dump() if hasattr(citation, "model_dump") else citation
            for citation in citations
        ],
        cited_sources=cited_sources,
        retrieved_section_ids=[chunk.section_id for chunk in retrieval[:5]],
        handoff_reason=_handoff_reason(handoff),
        accepted=result.get("answer_status") != "partial"
        and accepted(result.get("trace", []), str(result.get("answer", "")), handoff is not None),
        latency_first_token_s=first_token_latency,
        latency_full_answer_s=latency,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        llm_calls=usage.calls if usage is not None else None,
        usage_by_model=dict(usage.by_model) if usage is not None else None,
        reliability_events=result.get("reliability_events", []),
    )


def _metadata(settings: Settings, split: str, eval_text: str, corpus_hash: str) -> E2EMetadata:
    return E2EMetadata(
        git_sha=_git_sha(),
        config_hash=run_config_hash(settings),
        eval_file_hash=digest(eval_text),
        corpus_hash=corpus_hash,
        models=_model_names(settings),
        dataset_versions={
            source.name: source.repo_id + "@" + source.revision for source in settings.data.sources
        },
        split=split,
        date=datetime.now(UTC).isoformat(),
        customer_id=settings.evaluation.customer_id,
        threshold=settings.gate.threshold
        if settings.gate.threshold is not None
        else settings.gate.untuned_threshold,
        code_hash=source_hash(
            [
                *list((REPO_ROOT / "src/support_agent").rglob("*.py")),
                REPO_ROOT / "eval/e2e_eval.py",
                REPO_ROOT / "eval/e2e_records.py",
                REPO_ROOT / "eval/e2e_endpoint.py",
                REPO_ROOT / "eval/e2e_runs.py",
                REPO_ROOT / "eval/e2e_speed.py",
                REPO_ROOT / "eval/rerank_cache.py",
            ]
        ),
        prompt_hash=source_hash(list((REPO_ROOT / "src/support_agent/graph/prompts").glob("*"))),
        runtime=runtime_versions(),
        chaos=settings.chaos if settings.chaos.enabled else None,
        endpoint_host=endpoint_host(settings.llm),
    )


def _record_speed(
    metadata: E2EMetadata, speed: SpeedOptions, scores: dict[str, Any] | None
) -> None:
    """Record how items were collected; a resumed run keeps the least comparable setting."""
    metadata.workers = max(metadata.workers, speed.workers)
    metadata.latency_comparable = metadata.latency_comparable and speed.workers == 1
    metadata.rerank_scores = scores


def _save_and_render(
    run: Run,
    report: Path,
    root: Path,
    suffix: str,
    pointer: Path | None,
    renderer: RunRenderer,
) -> int:
    path = write_run(run.manifest, run.items, root=root, suffix=suffix, metrics=run.metrics)
    status = renderer(read_run(path), report)
    if pointer:
        write_text(pointer, str(path) + "\n")
    sys.stdout.write(f"Run record: {path}\n")
    return status or 0


def _priced_run(path: Path, settings: Settings) -> tuple[E2EMetadata, list[E2ERecord]]:
    """Read a finished run as-is and price its recorded usage with the current table."""
    lines = path.read_text(encoding="utf-8").splitlines()
    metadata = E2EMetadata.model_validate_json(lines[0])
    records = [E2ERecord.model_validate_json(line) for line in lines[1:] if line.strip()]
    for record in records:
        record.estimated_cost_usd = (
            cost_usd(record.usage_by_model, settings.costs) if record.usage_by_model else None
        )
    return metadata, records


def main(
    argv: list[str] | None = None,
    *,
    chaos_settings: Settings | None = None,
    renderer: RunRenderer = render_e2e,
    collection_command: list[str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["dev", "test", "all"], default="test")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--allow-untuned", action="store_true")
    parser.add_argument("--report", type=Path, default=Path("eval/reports/e2e.md"))
    parser.add_argument(
        "--eval-file",
        type=Path,
        default=None,
        help="frozen item file to run instead of eval_v1 (e.g. the near-miss holdout)",
    )
    parser.add_argument(
        "--trace", action="store_true", help="send each item to Langfuse when tracing is on"
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="rewrite the report from --output with current prices; no model calls",
    )
    parser.add_argument("--run-dir", type=Path, help="render a saved standard run without models")
    parser.add_argument("--run-root", type=Path, default=RUNS)
    parser.add_argument("--run-suffix")
    parser.add_argument(
        "--expect-dataset", help="require this registered dataset before collection"
    )
    parser.add_argument("--fresh", action="store_true", help="start a fresh, uniquely named cache")
    parser.add_argument("--run-pointer", type=Path, help="write the completed run directory here")
    add_speed_arguments(parser)
    args = parser.parse_args(argv)
    report = REPO_ROOT / args.report
    if args.run_dir:
        render_e2e(read_run(REPO_ROOT / args.run_dir), report)
        return 0
    suffix = args.run_suffix or uuid4().hex[:8]
    command = collection_command or ["eval-e2e", *(argv if argv is not None else sys.argv[1:])]
    settings = (chaos_settings or get_settings()).model_copy(deep=True)
    if args.report_only:
        output = REPO_ROOT / (args.output or Path(f"eval/runs/e2e_{args.split}.jsonl"))
        metadata, records = _priced_run(output, settings)
        if metadata.chaos and metadata.chaos.enabled:
            parser.error("Use make chaos to render fault-injected runs")
        return _save_and_render(
            prepare_e2e(metadata, records, command=command),
            report,
            args.run_root,
            suffix,
            args.run_pointer,
            renderer,
        )
    if settings.chaos.enabled and chaos_settings is None:
        parser.error("Use make chaos to collect a fault-injected run")
    speed = speed_options(args, settings, parser)
    dirty = is_dirty()
    if settings.gate.threshold is None and not args.allow_untuned:
        raise RuntimeError("gate.threshold is unset; run `make sweep` before e2e evaluation")
    sets_dir = REPO_ROOT / settings.evaluation.sets_dir
    eval_path = REPO_ROOT / args.eval_file if args.eval_file else sets_dir / "eval_v1.jsonl"
    eval_text = eval_path.read_text(encoding="utf-8")
    if args.expect_dataset and args.expect_dataset not in dataset_version(digest(eval_text)):
        raise ValueError(f"Eval file does not match registered dataset {args.expect_dataset}")
    # Every frozen file is built from the same corpus recorded in the main manifest.
    manifest = json.loads((sets_dir / "manifest.json").read_text(encoding="utf-8"))
    items = load_items(eval_path)
    if args.split != "all":
        items = [item for item in items if item.split == args.split]
    stem = "chaos" if settings.chaos.enabled else args.expect_dataset or "e2e"
    cache_name = f"{stem}-{args.split}-{suffix}.jsonl" if args.fresh else f"e2e_{args.split}.jsonl"
    cache_root = args.run_root if settings.chaos.enabled else RUNS
    output = REPO_ROOT / (args.output or cache_root / cache_name)
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata = _metadata(settings, args.split, eval_text, manifest["corpus_hash"])
    metadata.build_id = configured_build_id(settings)
    existing: dict[str, E2ERecord] = {}
    resumed = output.exists()
    if resumed and settings.chaos.enabled:
        raise ValueError("Chaos collection requires a fresh run suffix")
    if resumed:
        metadata, existing = load_cached_run(output, metadata, items)
    if not items:
        raise ValueError("No eval items match the requested split")
    pending = [item for item in items if item.id not in existing]
    threads = EvalThreads(stem)
    saved_scores = metadata.rerank_scores
    with (
        rerank_scores(settings, speed.rerank_cache) as scores,
        GraphDeps(
            settings,
            allow_untuned_gate=args.allow_untuned,
            reranker_factory=scores.factory(),
        ) as deps,
    ):
        graph = build_graph(deps)

        def collect(item: Any) -> E2ERecord:
            thread_id = threads(args.split, item.id)
            trace = (
                tracing.start_turn(
                    settings,
                    name="e2e_item",
                    conversation_id=thread_id,
                    customer_id=settings.evaluation.customer_id,
                    input_text=item.question,
                )
                if args.trace
                else tracing.TurnTrace()
            )
            result, latency, usage = _run_item(
                graph, item, settings.evaluation.customer_id, thread_id, trace
            )
            return _record(item, result, latency, usage.first_token_at, usage.tokens(), usage)

        def save(item: Any, record: E2ERecord) -> None:
            if record.build_id is not None and record.build_id != metadata.build_id:
                raise ValueError("Index build changed during collection; choose a fresh output")
            record.estimated_cost_usd = (
                cost_usd(record.usage_by_model, settings.costs) if record.usage_by_model else None
            )
            existing[item.id] = record
            _record_speed(metadata, speed, merge_rerank_scores(saved_scores, scores.summary()))
            temporary = output.with_suffix(output.suffix + ".tmp")
            write_text(
                temporary,
                "\n".join(
                    [
                        metadata.model_dump_json(),
                        # Input order, so the file never depends on which item finished first.
                        *[existing[i.id].model_dump_json() for i in items if i.id in existing],
                    ]
                )
                + "\n",
            )
            temporary.replace(output)

        run_items(pending, collect, workers=speed.workers, done=save)
        if pending:
            _record_speed(metadata, speed, merge_rerank_scores(saved_scores, scores.summary()))
    tracing.flush()
    records = [existing[item.id] for item in items]
    provenance_dirty = dirty if not resumed else None
    run = prepare_e2e(
        metadata,
        records,
        dirty=provenance_dirty,
        command=command,
        cost_note="price or usage unavailable"
        if any(
            price.input_per_million_usd is not None and price.output_per_million_usd is not None
            for price in settings.costs.prices.values()
        )
        else "price not set",
    )
    return _save_and_render(run, report, args.run_root, suffix, args.run_pointer, renderer)


if __name__ == "__main__":
    raise SystemExit(main())
