"""Compare classifier prompts on frozen dev questions and authored action controls."""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from eval.common import load_items
from eval.intent_eval import runtime_versions, source_hash
from support_agent.config import REPO_ROOT, get_settings
from support_agent.data.doc_models import digest, json_text, write_text
from support_agent.graph.intents import INTENT_TO_PATH, Intent
from support_agent.graph.intents import Path as Route
from support_agent.graph.nodes.classify import Classifier
from support_agent.llm import get_chat_model


class RoutingItem(BaseModel):
    id: str
    text: str
    source: str
    group: str
    expected_path: Route | None = None


class RoutingRecord(BaseModel):
    item: RoutingItem
    predicted: Intent
    parse_failed: bool
    confidence: float = Field(ge=0, le=1)
    latency_s: float = Field(ge=0)
    error_type: str | None = None
    model_name: str | None = None


def metrics(records: list[RoutingRecord]) -> dict[str, Any]:
    labelled = [r for r in records if r.item.expected_path is not None]
    correct = sum(
        not r.parse_failed and INTENT_TO_PATH[r.predicted] == r.item.expected_path for r in labelled
    )
    return {
        "labelled": len(labelled),
        "correct": correct,
        "path_accuracy": correct / len(labelled) if labelled else None,
        "failures": sum(r.parse_failed for r in records),
        "unlabelled_paths": dict(
            Counter(
                INTENT_TO_PATH[r.predicted].value for r in records if r.item.expected_path is None
            )
        ),
    }


def validate_pair(
    before_meta: dict[str, Any],
    before: list[RoutingRecord],
    after_meta: dict[str, Any],
    after: list[RoutingRecord],
) -> None:
    for key in ("eval_file_hash", "controls_hash", "config_hash", "model", "provider"):
        if before_meta[key] != after_meta[key]:
            raise ValueError(f"Routing comparison changed {key}")
    for key in ("model_options", "runtime", "code_hash", "dataset_versions"):
        if before_meta.get(key) != after_meta.get(key):
            raise ValueError(f"Routing comparison changed {key}")
    for records in (before, after):
        if len({r.item.id for r in records}) != len(records):
            raise ValueError("Routing comparison contains duplicate items")
    if {r.item.id: r.item.model_dump() for r in before} != {
        r.item.id: r.item.model_dump() for r in after
    }:
        raise ValueError("Routing comparison requires identical frozen items")


def load_run(path: Path) -> tuple[dict[str, Any], list[RoutingRecord]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return json.loads(lines[0]), [RoutingRecord.model_validate_json(line) for line in lines[1:]]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args(argv)
    if args.report_only:
        from eval.routing_report import write_report

        metadata, records = load_run(REPO_ROOT / args.output)
        write_report(
            metadata,
            records,
            REPO_ROOT / args.report,
            REPO_ROOT / args.baseline if args.baseline else None,
        )
        return 0
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    load_dotenv(REPO_ROOT / ".env")
    settings = get_settings()
    eval_path = REPO_ROOT / settings.evaluation.sets_dir / "eval_v1.jsonl"
    controls = REPO_ROOT / "eval/drafts/routing_controls.yaml"
    items = [
        RoutingItem(
            id=i.id,
            text=i.question,
            source="dev_answerable" if i.answerable else "dev_no_answer",
            group=i.group,
            expected_path=Route.KNOWLEDGE if i.answerable else None,
        )
        for i in load_items(eval_path)
        if i.split == "dev"
    ]
    items += [
        RoutingItem(source="controls", group="controls", **row)
        for row in yaml.safe_load(controls.read_text())
    ]
    if not items or len({i.id for i in items}) != len(items):
        raise ValueError("Routing experiment needs unique nonempty items")
    prompt = (REPO_ROOT / args.prompt).read_text()
    metadata = {
        "git_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip(),
        "code_hash": source_hash(
            [
                REPO_ROOT / "eval/routing_eval.py",
                REPO_ROOT / "eval/routing_report.py",
                REPO_ROOT / "src/support_agent/graph/nodes/classify.py",
                REPO_ROOT / "src/support_agent/graph/intents.py",
                REPO_ROOT / "src/support_agent/llm.py",
            ]
        ),
        "config_hash": digest(json_text(settings.model_dump(mode="json"))),
        "eval_file_hash": digest(eval_path.read_text()),
        "controls_hash": digest(controls.read_text()),
        "prompt_hash": digest(prompt),
        "prompt_path": str(args.prompt),
        "split": "dev plus authored controls",
        "date": datetime.now(UTC).isoformat(),
        "provider": os.environ.get("LLM_PROVIDER") or settings.llm.provider,
        "model": os.environ.get("LLM_FAST_MODEL") or settings.llm.fast_model,
        "model_options": {"temperature": settings.llm.temperature, **settings.llm.model_kwargs},
        "dataset_versions": {s.name: s.repo_id + "@" + s.revision for s in settings.data.sources},
        "runtime": runtime_versions(),
    }
    output = REPO_ROOT / args.output
    existing: dict[str, RoutingRecord] = {}
    if output.exists():
        saved_meta, saved = load_run(output)
        if {k: v for k, v in saved_meta.items() if k != "date"} != {
            k: v for k, v in metadata.items() if k != "date"
        }:
            raise ValueError("Routing cache provenance changed; choose a new output path")
        if len({r.item.id for r in saved}) != len(saved):
            raise ValueError("Routing cache contains duplicate items")
        expected = {i.id: i for i in items}
        if any(r.item != expected.get(r.item.id) for r in saved):
            raise ValueError("Routing cache items changed")
        existing = {r.item.id: r for r in saved}
        metadata = saved_meta
    pending = [i for i in items if i.id not in existing]
    if pending:
        classifier = Classifier(get_chat_model("fast", settings), settings)
        classifier.prompt = prompt

        def measure(item: RoutingItem) -> RoutingRecord:
            start = perf_counter()
            result = classifier.classify(item.text)
            return RoutingRecord(
                item=item,
                predicted=result.intent,
                parse_failed=result.parse_failed,
                confidence=result.confidence,
                latency_s=perf_counter() - start,
                error_type=result.error_type,
                model_name=result.model_name,
            )

        with ThreadPoolExecutor(max_workers=settings.intent_eval.max_concurrency) as pool:
            for record in pool.map(measure, pending):
                existing[record.item.id] = record
                temporary = output.with_suffix(output.suffix + ".tmp")
                write_text(
                    temporary,
                    json.dumps(metadata)
                    + "\n"
                    + "".join(
                        existing[i.id].model_dump_json() + "\n" for i in items if i.id in existing
                    ),
                )
                temporary.replace(output)
                logging.info("routing %d/%d", len(existing), len(items))
    from eval.routing_report import write_report

    write_report(
        metadata,
        [existing[i.id] for i in items],
        REPO_ROOT / args.report,
        REPO_ROOT / args.baseline if args.baseline else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
