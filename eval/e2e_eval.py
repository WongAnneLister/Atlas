"""Run the full graph over a frozen split and write resumable JSONL records."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from eval.common import load_items
from eval.e2e_records import E2EMetadata, E2ERecord, load_cached_run
from eval.e2e_report import render_e2e
from eval.e2e_runs import prepare_e2e
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
from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.data.doc_models import digest, json_text, write_text
from support_agent.graph.build import build_graph
from support_agent.graph.deps import GraphDeps
from support_agent.observability import tracing
from support_agent.observability.cost import UsageLedger, cost_usd
from support_agent.orders.service import OrderService


def _git_sha() -> str:
    return subprocess.check_output(
        ["git", "-c", f"safe.directory={REPO_ROOT}", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        text=True,
    ).strip()


def _model_names(settings: Settings) -> dict[str, str]:
    return {
        "fast": os.environ.get("LLM_FAST_MODEL") or settings.llm.fast_model or "unset",
        "main": os.environ.get("LLM_MAIN_MODEL") or settings.llm.main_model or "unset",
    }


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
        item=item,
        intent=getattr(result.get("intent"), "value", result.get("intent")),
        path=getattr(result.get("path"), "value", result.get("path")),
        trace=list(result.get("trace", [])),
        classification_failed=result.get("classification_failed"),
        classification_error_type=result.get("classification_error_type"),
        retrieval_error_type=result.get("retrieval_error_type"),
        answer_status=result.get("answer_status"),
        answer_error_type=result.get("answer_error_type"),
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
        accepted=accepted(
            result.get("trace", []), str(result.get("answer", "")), handoff is not None
        ),
        latency_first_token_s=first_token_latency,
        latency_full_answer_s=latency,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        llm_calls=usage.calls if usage is not None else None,
        usage_by_model=dict(usage.by_model) if usage is not None else None,
    )


def _metadata(settings: Settings, split: str, eval_text: str, corpus_hash: str) -> E2EMetadata:
    return E2EMetadata(
        git_sha=_git_sha(),
        config_hash=digest(json_text(settings.model_dump(mode="json"))),
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
            ]
        ),
        prompt_hash=source_hash(list((REPO_ROOT / "src/support_agent/graph/prompts").glob("*"))),
        runtime=runtime_versions(),
    )


def _save_and_render(run: Run, report: Path, root: Path, suffix: str, pointer: Path | None) -> None:
    path = write_run(run.manifest, run.items, root=root, suffix=suffix, metrics=run.metrics)
    render_e2e(read_run(path), report)
    if pointer:
        write_text(pointer, str(path) + "\n")
    sys.stdout.write(f"Run record: {path}\n")


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


def main(argv: list[str] | None = None) -> int:
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
    args = parser.parse_args(argv)
    report = REPO_ROOT / args.report
    if args.run_dir:
        render_e2e(read_run(REPO_ROOT / args.run_dir), report)
        return 0
    suffix = args.run_suffix or uuid4().hex[:8]
    command = ["eval-e2e", *(argv if argv is not None else sys.argv[1:])]
    settings = get_settings().model_copy(deep=True)
    if args.report_only:
        output = REPO_ROOT / (args.output or Path(f"eval/runs/e2e_{args.split}.jsonl"))
        metadata, records = _priced_run(output, settings)
        _save_and_render(
            prepare_e2e(metadata, records, command=command),
            report,
            args.run_root,
            suffix,
            args.run_pointer,
        )
        return 0
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
    stem = args.expect_dataset or "e2e"
    cache_name = f"{stem}-{args.split}-{suffix}.jsonl" if args.fresh else f"e2e_{args.split}.jsonl"
    output = REPO_ROOT / (args.output or RUNS / cache_name)
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata = _metadata(settings, args.split, eval_text, manifest["corpus_hash"])
    existing: dict[str, E2ERecord] = {}
    resumed = output.exists()
    if resumed:
        metadata, existing = load_cached_run(output, metadata, items)
    if not items:
        raise ValueError("No eval items match the requested split")
    pending = [item for item in items if item.id not in existing]
    with GraphDeps(
        settings,
        order_service=OrderService(settings=settings.orders),
        allow_untuned_gate=args.allow_untuned,
    ) as deps:
        graph = build_graph(deps)
        for item in pending:
            thread_id = f"e2e:{args.split}:{item.id}"
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
            record = _record(item, result, latency, usage.first_token_at, usage.tokens(), usage)
            record.estimated_cost_usd = (
                cost_usd(record.usage_by_model, settings.costs) if record.usage_by_model else None
            )
            existing[item.id] = record
            temporary = output.with_suffix(output.suffix + ".tmp")
            write_text(
                temporary,
                "\n".join(
                    [
                        metadata.model_dump_json(),
                        *[existing[i.id].model_dump_json() for i in items if i.id in existing],
                    ]
                )
                + "\n",
            )
            temporary.replace(output)
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
    _save_and_render(run, report, args.run_root, suffix, args.run_pointer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
