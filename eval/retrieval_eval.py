"""Run the frozen-set retrieval experiment; always measure dev alongside test."""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
from contextlib import ExitStack
from datetime import UTC, datetime

from eval.common import load_items, set_hash
from eval.retrieval_experiment import Experiment
from eval.retrieval_index import (
    collection_for_prefix,
    inference_runtime,
    prepare_experiment_index,
)
from eval.retrieval_records import RetrievalRun, RunMetadata
from eval.retrieval_report import write_reports
from eval.schema import EvalItem
from eval.validate_set import validate_current
from support_agent.config import REPO_ROOT, get_settings
from support_agent.data.doc_models import digest, json_text, write_text
from support_agent.retrieval.chunking import Chunk
from support_agent.retrieval.embed import BgeM3Embedder
from support_agent.retrieval.milvus_store import MilvusStore
from support_agent.retrieval.rerank import BgeReranker

log = logging.getLogger(__name__)


def select_items(items: list[EvalItem], split: str) -> list[EvalItem]:
    if split not in ("dev", "test", "all"):
        raise ValueError("Expected dev, test or all split")
    return sorted(
        [item for item in items if item.answerable and (split != "dev" or item.split == "dev")],
        key=lambda item: (item.split != "dev", item.id),
    )


def source_hash(paths: list) -> str:
    return digest(
        "".join(
            str(path.relative_to(REPO_ROOT)) + digest(path.read_text()) for path in sorted(paths)
        )
    )


def result_snapshot(execution_hash: str, metadata: RunMetadata) -> str:
    return digest(
        json_text(
            [
                execution_hash,
                metadata.eval_file_hash,
                metadata.corpus_hash,
                metadata.index_identities.get("baseline"),
                metadata.runtime,
            ]
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["dev", "test", "all"], default="test")
    parser.add_argument("--ablations", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = get_settings().model_copy(deep=True)
    if args.ablations is not None:
        settings.retrieval_eval.run_ablations = args.ablations
    cache = REPO_ROOT / settings.retrieval_eval.cache_dir
    latest = cache / "latest_run.json"
    if args.report_only:
        run = RetrievalRun.model_validate_json(latest.read_text())
        write_reports(run, REPO_ROOT / "eval/reports", REPO_ROOT / "docs/RETRIEVAL.md")
        return 0
    failures = validate_current()
    if failures:
        raise ValueError("Frozen evaluation validation failed: " + "; ".join(failures))
    folder = REPO_ROOT / settings.evaluation.sets_dir
    eval_text = (folder / "eval_v1.jsonl").read_text()
    all_items = load_items(folder / "eval_v1.jsonl")
    items = select_items(all_items, args.split)
    if not items or settings.retrieval.rerank_top_k < max(settings.retrieval_eval.metric_ks):
        raise ValueError("Need answerable items and enough rerank results for every metric cutoff")
    manifest = json.loads((folder / "manifest.json").read_text())
    chunks = [
        Chunk.model_validate_json(line)
        for line in (REPO_ROOT / settings.data.processed_dir / "chunks.jsonl")
        .read_text()
        .splitlines()
    ]
    modules = list((REPO_ROOT / "src/support_agent/retrieval").glob("*.py"))
    execution_hash = source_hash([*modules, REPO_ROOT / "eval/retrieval_experiment.py"])
    meta = RunMetadata(
        git_sha=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip(),
        code_hash=source_hash([*modules, *(REPO_ROOT / "eval").glob("*.py")]),
        config_hash=digest(json_text(settings.model_dump(mode="json"))),
        eval_file_hash=digest(eval_text),
        frozen_set_hash=set_hash(all_items),
        corpus_hash=manifest["corpus_hash"],
        date=datetime.now(UTC).isoformat(),
        dataset_versions=manifest["dataset_versions"],
        models={
            "embedding": settings.retrieval.embedding_model
            + "@"
            + settings.retrieval.embedding_revision,
            "reranker": settings.retrieval.reranker_model
            + "@"
            + settings.retrieval.reranker_revision,
        },
        settings=settings.model_dump(mode="json"),
        reviewed=sum(i.reviewed for i in all_items),
        total_items=len(all_items),
        index_identities={},
        runtime=inference_runtime(),
    )
    with ExitStack() as resources:
        embedder, reranker = BgeM3Embedder(settings.retrieval), BgeReranker(settings.retrieval)
        measured_settings = settings.model_copy(deep=True)
        measured_settings.milvus.collection = collection_for_prefix(
            settings, settings.chunk.prepend_heading
        )
        store = MilvusStore(measured_settings)
        resources.callback(store.close)
        meta.index_identities["baseline"] = prepare_experiment_index(
            settings, chunks, embedder, store, cache, settings.chunk.prepend_heading
        )
        meta.runtime["milvus_server"] = store.server_version()
        if settings.retrieval_eval.local_chunk_text:
            store.use_chunk_snapshot(chunks)
        snapshot = result_snapshot(execution_hash, meta)
        baseline = Experiment(
            measured_settings, store, embedder, reranker, cache / "results", snapshot
        )
        variants = {mode: (baseline, mode) for mode in ("dense", "bm25", "hybrid", "hybrid_rerank")}
        if settings.retrieval_eval.run_ablations:
            alternate = settings.model_copy(deep=True)
            alternate.chunk.prepend_heading = not settings.chunk.prepend_heading
            alternate.milvus.collection = collection_for_prefix(
                settings, alternate.chunk.prepend_heading
            )
            alt_store = MilvusStore(alternate)
            resources.callback(alt_store.close)
            identity = prepare_experiment_index(
                settings, chunks, embedder, alt_store, cache, alternate.chunk.prepend_heading
            )
            if settings.retrieval_eval.local_chunk_text:
                alt_store.use_chunk_snapshot(chunks)
            heading_label = "heading_on" if alternate.chunk.prepend_heading else "heading_off"
            meta.index_identities[heading_label] = identity
            variants["hybrid_" + heading_label] = (
                Experiment(
                    alternate,
                    alt_store,
                    embedder,
                    reranker,
                    cache / "results",
                    snapshot + identity,
                    bm25_source=baseline,
                ),
                "hybrid",
            )
            raw_query = measured_settings.model_copy(deep=True)
            raw_query.retrieval.bm25_normalise_model_numbers = not (
                settings.retrieval.bm25_normalise_model_numbers
            )
            normaliser_label = (
                "hybrid_normaliser_on"
                if raw_query.retrieval.bm25_normalise_model_numbers
                else "hybrid_normaliser_off"
            )
            variants[normaliser_label] = (
                Experiment(
                    raw_query,
                    store,
                    embedder,
                    reranker,
                    cache / "results",
                    snapshot,
                    dense_source=baseline,
                ),
                "hybrid",
            )
        meta.variant_config_hashes = {
            name: digest(json_text(experiment.settings.model_dump(mode="json")))
            for name, (experiment, _) in variants.items()
        }
        records = []
        for index, item in enumerate(items, 1):
            for name, (experiment, mode) in variants.items():
                record = experiment.retrieve(mode, item).model_copy(update={"mode": name})
                records.append(record)
                log.info(
                    "%s %d/%d %s mode=%s cached=%s latency=%.3fs",
                    item.split,
                    index,
                    len(items),
                    item.id,
                    name,
                    record.cache_hit,
                    record.latency_s,
                )
        run = RetrievalRun(metadata=meta, requested_split=args.split, records=records)
        write_text(latest, run.model_dump_json() + "\n")
        write_reports(run, REPO_ROOT / "eval/reports", REPO_ROOT / "docs/RETRIEVAL.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
