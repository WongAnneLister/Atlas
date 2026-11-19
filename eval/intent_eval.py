"""Evaluate the frozen intent holdout with the real fast model and provenance-bound caches."""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from dotenv import load_dotenv

from eval.intent_inputs import load_benchmark
from eval.intent_records import IntentItem, IntentRecord, IntentRun
from eval.legacy_core import import_intent, render_intent, save_intent
from eval.run_record import is_dirty
from eval.validate_set import validate_current
from support_agent.config import REPO_ROOT, get_settings
from support_agent.data.doc_models import digest, json_text, write_text
from support_agent.graph.nodes.classify import Classifier
from support_agent.llm import get_chat_model

log = logging.getLogger(__name__)


def runtime_versions() -> dict[str, str]:
    installed = {}
    for name in (
        "langchain",
        "langchain-core",
        "langgraph",
        "langchain-deepseek",
        "langchain-openai",
        "openai",
    ):
        try:
            installed[name] = version(name)
        except PackageNotFoundError:
            continue
    return installed


def source_hash(paths: list[Path]) -> str:
    return digest(
        "".join(str(p.relative_to(REPO_ROOT)) + digest(p.read_text()) for p in sorted(paths))
    )


def measure(item: IntentItem, classifier: Classifier, cache: Path, provenance: str) -> IntentRecord:
    path = cache / f"{digest(provenance + ':' + item.id)}.json"
    if path.exists():
        record = IntentRecord.model_validate_json(path.read_text())
        if record.provenance != provenance or record.item != item:
            raise ValueError("Intent cache provenance mismatch")
        return record.model_copy(update={"cache_hit": True})
    start = perf_counter()
    result = classifier.classify(item.text)
    record = IntentRecord(
        item=item,
        predicted=result.intent,
        confidence=result.confidence,
        parse_failed=result.parse_failed,
        error_type=result.error_type,
        model_name=result.model_name,
        latency_s=perf_counter() - start,
        provenance=provenance,
    )
    write_text(path, record.model_dump_json() + "\n")
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--run-dir", type=Path, help="render an existing intent run")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = get_settings()
    cache = REPO_ROOT / settings.intent_eval.cache_dir
    latest = cache / "latest_run.json"
    report_path = REPO_ROOT / "eval/reports/intent.md"
    pointer = cache / "latest_run_path.txt"
    if args.report_only or args.run_dir:
        if args.run_dir:
            run_path = REPO_ROOT / args.run_dir
        elif pointer.exists():
            run_path = REPO_ROOT / Path(pointer.read_text().strip())
        else:
            run_path = import_intent(latest, suffix=uuid4().hex[:8])
            write_text(pointer, run_path.relative_to(REPO_ROOT).as_posix() + "\n")
        render_intent(run_path, report_path)
        return 0
    load_dotenv(REPO_ROOT / ".env")
    started_at = datetime.now(UTC)
    dirty = is_dirty()
    command = ["python", "-m", "eval.intent_eval", *(sys.argv[1:] if argv is None else argv)]
    failures = validate_current()
    if failures:
        raise ValueError("Frozen retrieval set validation failed: " + "; ".join(failures))
    items, manifest = load_benchmark(settings)
    model = get_chat_model("fast", settings)
    provider = os.environ.get("LLM_PROVIDER") or settings.llm.provider
    model_name = os.environ.get("LLM_FAST_MODEL") or settings.llm.fast_model
    graph_files = list((REPO_ROOT / "src/support_agent/graph").rglob("*.py"))
    execution_hash = source_hash(
        [
            REPO_ROOT / "src/support_agent/llm.py",
            REPO_ROOT / "src/support_agent/graph/nodes/classify.py",
            REPO_ROOT / "src/support_agent/graph/intents.py",
            REPO_ROOT / "eval/intent_records.py",
            REPO_ROOT / "eval/intent_eval.py",
        ]
    )
    runtime = runtime_versions()
    metadata = {
        "git_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip(),
        "code_hash": source_hash(
            [
                *graph_files,
                *list((REPO_ROOT / "eval").glob("intent_*.py")),
                REPO_ROOT / "src/support_agent/llm.py",
                REPO_ROOT / "src/support_agent/data/intent_map.py",
                REPO_ROOT / "src/support_agent/config.py",
                REPO_ROOT / "src/support_agent/data/doc_models.py",
                REPO_ROOT / "eval/common.py",
                REPO_ROOT / "eval/schema.py",
            ]
        ),
        "config_hash": digest(json_text(settings.model_dump(mode="json"))),
        "prompt_hash": manifest["prompt_hash"],
        "dataset_hash": manifest["dataset_hash"],
        "date": started_at.isoformat(),
        "provider": provider,
        "model": model_name,
        "model_options": {"temperature": settings.llm.temperature, **settings.llm.model_kwargs},
        "dataset_versions": manifest["dataset_versions"],
        "sample_stats": manifest["stats"],
        "input_hashes": {key: value for key, value in manifest.items() if key.endswith("_hash")},
        "endpoint": getattr(model, "api_base", None) or getattr(model, "openai_api_base", None),
        "target_accuracy": settings.intent_eval.target_accuracy,
        "runtime": runtime,
    }
    provenance = digest(
        json_text(
            [
                execution_hash,
                metadata["config_hash"],
                manifest,
                provider,
                model_name,
                metadata["endpoint"],
                runtime,
            ]
        )
    )
    classifier = Classifier(model, settings)
    records = []
    with ThreadPoolExecutor(max_workers=settings.intent_eval.max_concurrency) as pool:
        for index, record in enumerate(
            pool.map(lambda i: measure(i, classifier, cache / "predictions", provenance), items), 1
        ):
            records.append(record)
            log.info(
                "%d/%d id=%s cached=%s failed=%s",
                index,
                len(items),
                record.item.id,
                record.cache_hit,
                record.parse_failed,
            )
    metadata["response_models"] = sorted({r.model_name for r in records if r.model_name})
    run = IntentRun(metadata=metadata, records=records)
    write_text(latest, run.model_dump_json() + "\n")
    run_path = save_intent(run, command, dirty=dirty, suffix=started_at.strftime("%H%M%S%f"))
    write_text(pointer, run_path.relative_to(REPO_ROOT).as_posix() + "\n")
    render_intent(run_path, report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
