"""Run the full graph over a frozen split and write resumable JSONL records."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from eval.common import load_items
from eval.e2e_diagnostics import diagnostic_lines
from eval.e2e_records import E2EMetadata, E2ERecord, load_cached_run
from eval.intent_eval import runtime_versions, source_hash
from eval.metrics import accepted, mrr, outcome_rates, percentile, recall_at_k
from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.data.doc_models import digest, json_text, write_text
from support_agent.graph.build import build_graph
from support_agent.graph.deps import GraphDeps
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


class UsageCollector(BaseCallbackHandler):
    def __init__(self) -> None:
        self.first_token_at: float | None = None
        self.input_tokens = 0
        self.output_tokens = 0
        self.has_usage = False
        self.started = time.perf_counter()

    def on_llm_new_token(self, token: Any, **kwargs: Any) -> None:
        if token and self.first_token_at is None:
            self.first_token_at = time.perf_counter() - self.started

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        usage = getattr(response, "llm_output", None) or {}
        usage = usage.get("token_usage", {}) if isinstance(usage, dict) else {}
        generations = getattr(response, "generations", [])
        for group in generations:
            for generation in group:
                message_usage = getattr(generation.message, "usage_metadata", None)
                if isinstance(message_usage, dict):
                    usage = message_usage
                    break
            if usage:
                break
        input_value = (
            usage.get("input_tokens", usage.get("prompt_tokens"))
            if isinstance(usage, dict)
            else None
        )
        output_value = (
            usage.get("output_tokens", usage.get("completion_tokens"))
            if isinstance(usage, dict)
            else None
        )
        if isinstance(input_value, int) and isinstance(output_value, int):
            self.input_tokens += input_value
            self.output_tokens += output_value
            self.has_usage = True

    def tokens(self) -> tuple[int | None, int | None]:
        return (self.input_tokens, self.output_tokens) if self.has_usage else (None, None)


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


def _cost(settings: Settings, input_tokens: int | None, output_tokens: int | None) -> float | None:
    if input_tokens is None or output_tokens is None:
        return None
    input_rate = settings.evaluation.input_cost_per_million_usd.get("main")
    output_rate = settings.evaluation.output_cost_per_million_usd.get("main")
    if input_rate is None or output_rate is None:
        return None
    return input_tokens / 1_000_000 * input_rate + output_tokens / 1_000_000 * output_rate


def _handoff_reason(value: Any) -> str | None:
    reason = getattr(value, "reason", None)
    if reason is None and isinstance(value, dict):
        reason = value.get("reason")
    return getattr(reason, "value", reason) if reason is not None else None


def _run_item(
    graph: Any, item: Any, customer_id: str, thread_id: str
) -> tuple[dict[str, Any], float, float | None, tuple[int | None, int | None]]:
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    usage = UsageCollector()
    config["callbacks"] = [usage]
    started = time.perf_counter()
    result = graph.invoke(
        {"messages": [HumanMessage(content=item.question)], "customer_id": customer_id},
        config,
    )
    while result.get("__interrupt__"):
        result = graph.invoke(Command(resume="none"), config)
    return result, time.perf_counter() - started, usage.first_token_at, usage.tokens()


def _record(
    item: Any,
    result: dict[str, Any],
    latency: float,
    first_token_latency: float | None,
    token_usage: tuple[int | None, int | None],
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


def _write_report(records: list[E2ERecord], metadata: E2EMetadata, path: Path) -> None:
    labels = [record.item.answerable for record in records]
    outcomes = [record.accepted for record in records]
    rates = outcome_rates(labels, outcomes)
    answerable = [record for record in records if record.item.answerable]
    recalls = [
        recall_at_k(record.retrieved_section_ids, record.item.gold_sections, 5)
        for record in answerable
    ]
    citation_validity = [
        (
            len(
                {source["section_id"] for source in record.cited_sources}
                & set(record.item.gold_sections)
            )
            / len({source["section_id"] for source in record.cited_sources})
            if {source["section_id"] for source in record.cited_sources}
            else 0.0
        )
        for record in answerable
    ]
    reciprocal_ranks = [
        mrr(record.retrieved_section_ids, record.item.gold_sections) for record in answerable
    ]
    latencies = [record.latency_full_answer_s for record in records]
    by_intent: dict[str, list[E2ERecord]] = defaultdict(list)
    for record in records:
        by_intent[record.intent or "unknown"].append(record)
    first_token_values = [
        record.latency_first_token_s
        for record in records
        if record.latency_first_token_s is not None
    ]
    lines = [
        "# End-to-end evaluation",
        "",
        "Generated by `make eval-e2e`. Full graph outcomes are reported without tuning on test.",
        "",
        f"- Git SHA: `{metadata.git_sha}`",
        f"- Config hash: `{metadata.config_hash}`",
        f"- Eval file hash: `{metadata.eval_file_hash}`",
        f"- Corpus hash: `{metadata.corpus_hash}`",
        f"- Split: {metadata.split} ({len(records)} items)",
        f"- Date (UTC): {metadata.date}",
        f"- Models: {json.dumps(metadata.models, sort_keys=True)}",
        f"- Dataset versions: {json.dumps(metadata.dataset_versions, sort_keys=True)}",
        f"- Customer fixture: `{metadata.customer_id}`",
        f"- Gate threshold: {metadata.threshold:.2f}",
        f"- Collection code hash: `{metadata.code_hash or 'not recorded in legacy run'}`",
        f"- Prompt hash: `{metadata.prompt_hash or 'not recorded in legacy run'}`",
        f"- Model runtime: `{metadata.runtime}`",
        "- First-token latency uses model streaming callbacks when available.",
        "- Providers without streaming callbacks report first-token latency as unavailable.",
        "- Recall@5 uses retrieved sections.",
        "- Citation validity measures cited-section overlap with gold sections.",
        "",
        "## Outcome metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| False accept | {rates.false_accept:.2%} |",
        f"| False reject | {rates.false_reject:.2%} |",
        f"| Accepted | {rates.pass_rate:.2%} ({rates.accepted_count}/{len(records)}) |",
        f"| Recall@5 from graph retrieval | {sum(recalls) / len(recalls):.4f} |"
        if recalls
        else "| Recall@5 from graph retrieval | pending |",
        f"| MRR@5 from graph retrieval | {sum(reciprocal_ranks) / len(reciprocal_ranks):.4f} |"
        if reciprocal_ranks
        else "| MRR@5 from graph retrieval | pending |",
        f"| Citation validity | {sum(citation_validity) / len(citation_validity):.4f} |"
        if citation_validity
        else "| Citation validity | pending |",
        f"| Latency P50 full answer | {percentile(latencies, 50):.4f}s |"
        if latencies
        else "| Latency P50 full answer | pending |",
        f"| Latency P95 full answer | {percentile(latencies, 95):.4f}s |"
        if latencies
        else "| Latency P95 full answer | pending |",
        (
            f"| Latency P50 first token | {percentile(first_token_values, 50):.4f}s |"
            if first_token_values
            else "| Latency P50 first token | unavailable |"
        ),
        (
            f"| Latency P95 first token | {percentile(first_token_values, 95):.4f}s |"
            if first_token_values
            else "| Latency P95 first token | unavailable |"
        ),
        "",
        "## Tokens and cost by intent",
        "",
        "| Intent | Items | Input tokens | Output tokens | Estimated cost |",
        "|---|---:|---:|---:|---:|",
    ]
    for intent, intent_records in sorted(by_intent.items()):
        inputs = [
            record.input_tokens for record in intent_records if record.input_tokens is not None
        ]
        outputs = [
            record.output_tokens for record in intent_records if record.output_tokens is not None
        ]
        costs = [
            record.estimated_cost_usd
            for record in intent_records
            if record.estimated_cost_usd is not None
        ]
        lines.append(
            f"| {intent} | {len(intent_records)} | {sum(inputs) if inputs else 'pending'} | "
            f"{sum(outputs) if outputs else 'pending'} | "
            f"{f'${sum(costs):.6f}' if costs else 'pending'} |"
        )
    lines.extend(
        [
            "",
            "## No-answer false accepts",
            "",
            "These outcomes are retained unchanged; test results do not tune the threshold.",
            "",
            "| Item | Intent | Path | Trace |",
            "|---|---|---|---|",
        ]
    )
    lines.extend(
        f"| {record.item.id} | {record.intent} | {record.path} | {' -> '.join(record.trace)} |"
        for record in records
        if not record.item.answerable and record.accepted
    )
    lines.extend(diagnostic_lines(records))
    write_text(path, "\n".join(lines) + "\n")


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
    args = parser.parse_args(argv)
    settings = get_settings().model_copy(deep=True)
    if settings.gate.threshold is None and not args.allow_untuned:
        raise RuntimeError("gate.threshold is unset; run `make sweep` before e2e evaluation")
    sets_dir = REPO_ROOT / settings.evaluation.sets_dir
    eval_path = REPO_ROOT / args.eval_file if args.eval_file else sets_dir / "eval_v1.jsonl"
    eval_text = eval_path.read_text(encoding="utf-8")
    # Every frozen file is built from the same corpus recorded in the main manifest.
    manifest = json.loads((sets_dir / "manifest.json").read_text(encoding="utf-8"))
    items = load_items(eval_path)
    if args.split != "all":
        items = [item for item in items if item.split == args.split]
    output = REPO_ROOT / (args.output or Path(f"eval/runs/e2e_{args.split}.jsonl"))
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata = _metadata(settings, args.split, eval_text, manifest["corpus_hash"])
    existing: dict[str, E2ERecord] = {}
    if output.exists():
        metadata, existing = load_cached_run(output, metadata, items)
    pending = [item for item in items if item.id not in existing]
    with GraphDeps(
        settings,
        order_service=OrderService(settings=settings.orders),
        allow_untuned_gate=args.allow_untuned,
    ) as deps:
        graph = build_graph(deps)
        for item in pending:
            result, latency, first_token_latency, token_usage = _run_item(
                graph, item, settings.evaluation.customer_id, f"e2e:{args.split}:{item.id}"
            )
            record = _record(item, result, latency, first_token_latency, token_usage)
            record.estimated_cost_usd = _cost(settings, record.input_tokens, record.output_tokens)
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
    records = [existing[item.id] for item in items]
    report = REPO_ROOT / args.report
    _write_report(records, metadata, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
