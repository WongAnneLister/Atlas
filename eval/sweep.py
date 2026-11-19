"""Sweep the evidence gate on cached dev scores and report held-out test results."""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from eval.common import load_items
from eval.metrics import Rates, outcome_rates, sweep_rates
from eval.schema import EvalItem
from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.data.doc_models import digest, json_text, write_text
from support_agent.gate.evidence import VETO_REASONS, evaluate
from support_agent.retrieval.chunking import Chunk
from support_agent.retrieval.embed import BgeM3Embedder
from support_agent.retrieval.factory import build_retriever
from support_agent.retrieval.milvus_store import MilvusStore
from support_agent.retrieval.rerank import BgeReranker
from support_agent.retrieval.scope import scope_chunks
from support_agent.retrieval.types import RetrievedChunk


class ChunkScore(BaseModel):
    """A retrieved chunk id and its rerank score; text is re-read from local chunks."""

    chunk_id: str
    rerank: float


class GateScore(BaseModel):
    record_type: str = "item"
    id: str
    group: str
    split: str
    answerable: bool
    score: float = Field(ge=0, le=1)
    signals: dict[str, float]
    ranked_section_ids: list[str] = Field(default_factory=list)
    chunks: list[ChunkScore] = Field(default_factory=list)
    vetoed: bool = False


class GateScoreMetadata(BaseModel):
    record_type: str = "metadata"
    git_sha: str
    config_hash: str
    eval_file_hash: str
    corpus_hash: str
    split: str
    date: str
    models: dict[str, str]
    dataset_versions: dict[str, str]


def thresholds() -> list[float]:
    return [round(index / 100, 2) for index in range(5, 96)]


def effective_score(record: GateScore) -> float:
    """A vetoed record never passes, whatever the threshold."""
    return -1.0 if record.vetoed else record.score


def rates_for_records(records: list[GateScore], threshold: float) -> Rates:
    sweep_rates([r.answerable for r in records], [r.score for r in records], threshold)
    return outcome_rates(
        [record.answerable for record in records],
        [not record.vetoed and record.score >= threshold for record in records],
    )


def select_threshold(records: list[GateScore], rule: str = "lowest") -> float | None:
    """Pick a grid threshold with zero dev false accepts.

    "lowest" takes the first such threshold. "midpoint" takes the grid value nearest the
    centre of the gap between the highest no-answer score and the next answerable score.
    """
    safe = [t for t in thresholds() if rates_for_records(records, t).false_accept == 0]
    if not safe:
        return None
    if rule == "lowest":
        return safe[0]
    if rule != "midpoint":
        raise ValueError(f"Unknown threshold rule: {rule}")
    highest_no_answer = max([0.0, *(effective_score(r) for r in records if not r.answerable)])
    above = [effective_score(r) for r in records if r.answerable]
    above = [value for value in above if value > highest_no_answer]
    if not above:
        return safe[0]
    centre = (highest_no_answer + min(above)) / 2
    return min(safe, key=lambda t: (abs(t - centre), t))


def production_chunks(retriever: Any, question: str, settings: Settings) -> list[RetrievedChunk]:
    """Retrieve exactly what the knowledge path sees: pool, store scope, then top k."""
    retrieval = settings.retrieval
    scope = retrieval.store_scope
    pool = max(retrieval.rerank_top_k, scope.pool_k) if scope.enabled else retrieval.rerank_top_k
    ranked = retriever.retrieve(question, pool)
    return scope_chunks(question, ranked, scope, retrieval.rerank_top_k)[0]


def load_local_chunks(settings: Settings, path: Path | None = None) -> dict[str, Chunk]:
    path = path or REPO_ROOT / settings.data.processed_dir / "chunks.jsonl"
    chunks = [
        Chunk.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    return {chunk.chunk_id: chunk for chunk in chunks}


def rescore(
    records: list[GateScore],
    items: list[EvalItem],
    settings: Settings,
    chunk_file: Path | None = None,
) -> list[GateScore]:
    """Recompute gate scores from cached retrieval snapshots with the current gate code."""
    questions = {item.id: item.question for item in items}
    texts = load_local_chunks(settings, chunk_file) if any(r.chunks for r in records) else {}
    rescored = []
    for record in records:
        chunks = [
            RetrievedChunk(**texts[c.chunk_id].model_dump(), scores={"rerank": c.rerank})
            for c in record.chunks
        ]
        result = evaluate(questions[record.id], chunks, settings.gate, allow_untuned=True)
        rescored.append(
            record.model_copy(
                update={
                    "score": result.score,
                    "signals": result.signals,
                    "vetoed": result.reason in VETO_REASONS,
                }
            )
        )
    return rescored


def _git_sha() -> str:
    return subprocess.check_output(
        ["git", "-c", f"safe.directory={REPO_ROOT}", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        text=True,
    ).strip()


def _eval_paths(settings: Settings, split: str) -> tuple[Path, list[EvalItem], str]:
    path = REPO_ROOT / settings.evaluation.sets_dir / "eval_v1.jsonl"
    items = [item for item in load_items(path) if item.split == split]
    manifest = json.loads((path.parent / "manifest.json").read_text(encoding="utf-8"))
    return path, items, manifest["corpus_hash"]


def score_config_hash(settings: Settings) -> str:
    """Hash every setting that can change retrieval; gate settings are rescored offline."""
    dumped = settings.model_dump(mode="json")
    dumped.pop("gate", None)
    dumped.pop("eval", None)
    return digest(json_text(dumped))


def validate_score_rows(records: list[GateScore], items: list[EvalItem], split: str) -> None:
    """Reject cached rows that could change the frozen split's denominators or labels."""
    expected = {item.id: item for item in items}
    ids = [record.id for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError("Score cache contains duplicate item ids")
    if any(
        record.id not in expected
        or record.split != expected[record.id].split
        or record.group != expected[record.id].group
        or record.answerable != expected[record.id].answerable
        for record in records
    ):
        raise ValueError("Score cache rows do not match the frozen split")


def collect_scores(
    settings: Settings,
    split: str,
    output: Path,
    selection: tuple[Path, list[EvalItem], str] | None = None,
) -> list[GateScore]:
    """Run retrieval once per question and cache the reranked snapshot and gate scores."""
    eval_path, items, corpus_hash = selection or _eval_paths(settings, split)
    if not items:
        raise ValueError(f"No {split} evaluation items found")

    metadata = GateScoreMetadata(
        git_sha=_git_sha(),
        config_hash=score_config_hash(settings),
        eval_file_hash=digest(eval_path.read_text(encoding="utf-8")),
        corpus_hash=corpus_hash,
        split=split,
        date=datetime.now(UTC).isoformat(),
        models={
            "embedding": settings.retrieval.embedding_model,
            "reranker": settings.retrieval.reranker_model,
        },
        dataset_versions={
            source.name: source.repo_id + "@" + source.revision for source in settings.data.sources
        },
    )
    records: list[GateScore] = []
    if output.exists():
        try:
            saved, cached = load_scores(output)
        except ValueError:
            cached = []
        else:
            if all(
                getattr(saved, name) == getattr(metadata, name)
                for name in ("config_hash", "eval_file_hash", "corpus_hash", "split")
            ):
                validate_score_rows(cached, items, split)
                records = cached
                metadata = saved
    completed = {record.id for record in records}
    pending = [item for item in items if item.id not in completed]
    if not pending:
        return records
    try:
        store = MilvusStore(settings)
    except Exception as error:
        raise RuntimeError("Milvus is unavailable; start it with `make up` and retry") from error
    try:
        retriever = build_retriever(
            "hybrid_rerank",
            settings=settings,
            store=store,
            embedder=BgeM3Embedder(settings.retrieval),
            reranker=BgeReranker(settings.retrieval),
        )
        for item in pending:
            chunks = production_chunks(retriever, item.question, settings)
            result = evaluate(item.question, chunks, settings.gate, allow_untuned=True)
            records.append(
                GateScore(
                    id=item.id,
                    group=item.group,
                    split=item.split,
                    answerable=item.answerable,
                    score=result.score,
                    signals=result.signals,
                    ranked_section_ids=[chunk.section_id for chunk in chunks],
                    chunks=[
                        ChunkScore(chunk_id=chunk.chunk_id, rerank=chunk.scores.get("rerank", 0.0))
                        for chunk in chunks
                    ],
                    vetoed=result.reason in VETO_REASONS,
                )
            )
            temporary = output.with_suffix(output.suffix + ".tmp")
            write_text(
                temporary,
                metadata.model_dump_json()
                + "\n"
                + "".join(record.model_dump_json() + "\n" for record in records),
            )
            temporary.replace(output)
            logging.getLogger(__name__).info("%s scores: %d/%d", split, len(records), len(items))
    finally:
        store.close()
    return records


def load_scores(path: Path) -> tuple[GateScoreMetadata, list[GateScore]]:
    metadata: GateScoreMetadata | None = None
    records: list[GateScore] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        data: dict[str, Any] = json.loads(line)
        if data.get("record_type") == "metadata":
            metadata = GateScoreMetadata.model_validate(data)
        else:
            records.append(GateScore.model_validate(data))
    if metadata is None or not records:
        raise ValueError(f"Gate score cache is empty or missing metadata: {path}")
    return metadata, records


def _format_rate(rate: float) -> str:
    return f"{rate:.2%}"


def _write_config_threshold(threshold: float | None, report: Path, git_sha: str) -> None:
    config_path = REPO_ROOT / "configs/default.yaml"
    text = config_path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(text)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("gate"), dict):
        raise ValueError("Config has no gate section")
    lines = text.splitlines(keepends=True)
    in_gate = False
    count = 0
    for index, line in enumerate(lines):
        if re.match(r"^gate:\s*(?:#.*)?$", line):
            in_gate = True
            continue
        if in_gate and re.match(r"^[^\s#][^:]*:", line):
            break
        if in_gate and re.match(r"^\s+threshold:", line):
            value = (
                "null # no zero-false-accept threshold; see "
                if threshold is None
                else f"{threshold:.2f} # selected by "
            )
            lines[index] = f"  threshold: {value}{report.as_posix()} at {git_sha}\n"
            count += 1
            break
    if count != 1:
        raise ValueError("Could not find gate.threshold in configs/default.yaml")
    parsed["gate"]["threshold"] = threshold
    updated = "".join(lines)
    if yaml.safe_load(updated)["gate"]["threshold"] != parsed["gate"]["threshold"]:
        raise ValueError("Updated gate threshold did not validate")
    write_text(config_path, updated)


def write_report(
    dev_meta: GateScoreMetadata,
    dev: list[GateScore],
    selected: float | None,
    test_meta: GateScoreMetadata | None,
    test: list[GateScore] | None,
    path: Path,
    rule: str = "lowest",
) -> None:
    highest_no_answer = max([0.0, *(effective_score(r) for r in dev if not r.answerable)])
    gap = selected - highest_no_answer if selected is not None else None
    lines = [
        "# Evidence threshold sweep",
        "",
        "Generated by `make sweep`. The threshold is tuned on dev only.",
        "",
        f"- Git SHA: `{dev_meta.git_sha}`",
        f"- Config hash: `{dev_meta.config_hash}`",
        f"- Eval file hash: `{dev_meta.eval_file_hash}`",
        f"- Corpus hash: `{dev_meta.corpus_hash}`",
        f"- Date (UTC): {dev_meta.date}",
        f"- Split used for tuning: {dev_meta.split} ({len(dev)} items)",
        f"- Models: {json.dumps(dev_meta.models, sort_keys=True)}",
        f"- Dataset versions: {json.dumps(dev_meta.dataset_versions, sort_keys=True)}",
        "",
        "## Selection",
        "",
        f"- Threshold rule: `{rule}`",
        f"- Dev items vetoed for absent named terms: {sum(r.vetoed for r in dev)} "
        f"(no-answer {sum(r.vetoed for r in dev if not r.answerable)})",
        f"- Selected threshold: **{selected:.2f}**"
        if selected is not None
        else "- Selected threshold: **none**",
        f"- Highest no-answer dev score: {highest_no_answer:.4f}",
        f"- Threshold minus highest no-answer score: {gap:.4f}"
        if gap is not None
        else "- Gap: not available",
        "",
        "| Threshold | False accept | False reject | Pass rate |",
        "|---:|---:|---:|---:|",
    ]
    lines.extend(
        f"| {threshold:.2f} | {_format_rate(rates_for_records(dev, threshold).false_accept)} | "
        f"{_format_rate(rates_for_records(dev, threshold).false_reject)} | "
        f"{_format_rate(rates_for_records(dev, threshold).pass_rate)} |"
        for threshold in thresholds()
    )
    lines.extend(
        ["", "## Highest no-answer scores on dev", "", "| Id | Group | Score |", "|---|---|---:|"]
    )
    lines.extend(
        f"| {record.id} | {record.group} | {record.score:.4f} |"
        for record in sorted(
            (r for r in dev if not r.answerable), key=lambda r: r.score, reverse=True
        )[:10]
    )
    lines.extend(["", "## Held-out test", ""])
    if test_meta is None or test is None:
        lines.append(
            "Test gate scores were not available. Run `make sweep` after collecting both splits."
        )
    else:
        test_rates = rates_for_records(test, selected) if selected is not None else None
        lines.extend(
            [
                f"- Cache Git SHA: `{test_meta.git_sha}`",
                f"- Test items: {len(test)}",
                "- False accept: "
                + (_format_rate(test_rates.false_accept) if test_rates else "not measured"),
                "- False reject: "
                + (_format_rate(test_rates.false_reject) if test_rates else "not measured"),
                "- Pass rate: "
                + (_format_rate(test_rates.pass_rate) if test_rates else "not measured"),
            ]
        )
        if test_rates and test_rates.false_accept:
            lines.append(
                "- Test false accepts are reported unchanged. Test never tunes thresholds."
            )
            lines.extend(["", "### Test false accepts", "", "| Id | Score |", "|---|---:|"])
            lines.extend(
                f"| {record.id} | {record.score:.4f} |"
                for record in test
                if not record.answerable
                and not record.vetoed
                and selected is not None
                and record.score >= selected
            )
    write_text(path, "\n".join(lines) + "\n")


def write_plot(dev: list[GateScore], path: Path, selected: float | None) -> None:
    import matplotlib.pyplot as plt

    values = [
        sweep_rates([r.answerable for r in dev], [r.score for r in dev], t) for t in thresholds()
    ]
    fig, axis = plt.subplots(figsize=(7, 4.5))
    axis.plot(thresholds(), [rate.false_accept for rate in values], label="false accept")
    axis.plot(thresholds(), [rate.false_reject for rate in values], label="false reject")
    if selected is not None:
        axis.axvline(selected, color="#444444", linestyle="--", label=f"selected {selected:.2f}")
    axis.set(xlabel="Gate threshold", ylabel="Rate", xlim=(0.05, 0.95), ylim=(0, 1))
    axis.grid(alpha=0.25)
    axis.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev-cache", type=Path, default=Path("eval/runs/gate_scores_dev.jsonl"))
    parser.add_argument("--test-cache", type=Path, default=Path("eval/runs/gate_scores_test.jsonl"))
    parser.add_argument("--no-collect", action="store_true")
    parser.add_argument("--run-dir", type=Path, help="render an existing sweep without tuning")
    args = parser.parse_args(argv)
    from eval.run_record import is_dirty
    from eval.sweep_runs import render_sweep, save_sweep

    report = REPO_ROOT / "eval/reports/threshold_sweep.md"
    plot = REPO_ROOT / "eval/reports/threshold_sweep.png"
    if args.run_dir:
        render_sweep(REPO_ROOT / args.run_dir, report, plot)
        return 0
    started_at = datetime.now(UTC)
    dirty = is_dirty()
    command = ["python", "-m", "eval.sweep", *(sys.argv[1:] if argv is None else argv)]
    settings = get_settings().model_copy(deep=True)
    dev_cache = REPO_ROOT / args.dev_cache
    test_cache = REPO_ROOT / args.test_cache
    eval_path, _, corpus_hash = _eval_paths(settings, "dev")
    expected_eval_hash = digest(eval_path.read_text(encoding="utf-8"))

    def cache_matches(path: Path, split: str) -> bool:
        if not path.exists():
            return False
        try:
            metadata, records = load_scores(path)
            _, expected_items, _ = _eval_paths(settings, split)
            validate_score_rows(records, expected_items, split)
        except (OSError, ValueError):
            return False
        return (
            len(records) == len(expected_items)
            and {record.id for record in records} == {item.id for item in expected_items}
            and metadata.split == split
            and metadata.config_hash == score_config_hash(settings)
            and metadata.eval_file_hash == expected_eval_hash
            and metadata.corpus_hash == corpus_hash
        )

    if not args.no_collect:
        if not cache_matches(dev_cache, "dev"):
            dev_cache.parent.mkdir(parents=True, exist_ok=True)
            collect_scores(settings, "dev", dev_cache)
        if not cache_matches(test_cache, "test"):
            test_cache.parent.mkdir(parents=True, exist_ok=True)
            collect_scores(settings, "test", test_cache)
    elif not cache_matches(dev_cache, "dev"):
        raise ValueError("No current dev cache matches this evaluation, corpus, and score config")
    every_item = load_items(eval_path)
    dev_meta, dev = load_scores(dev_cache)
    dev = rescore(dev, every_item, settings)
    if args.no_collect and not cache_matches(test_cache, "test"):
        test_meta, test = None, None
    else:
        test_meta, test = load_scores(test_cache) if test_cache.exists() else (None, None)
    if test is not None:
        test = rescore(test, every_item, settings)
    run_path = save_sweep(
        (dev_meta, dev),
        (test_meta, test) if test_meta and test is not None else None,
        settings.gate.threshold_rule,
        command,
        root=REPO_ROOT / "eval/runs",
        suffix=started_at.strftime("%H%M%S%f"),
        dirty=dirty,
        started_at=started_at,
        config_hash=digest(json_text(settings.model_dump(mode="json"))),
        git_sha=_git_sha(),
    )
    selected = render_sweep(run_path, report, plot)
    if test is not None:
        _write_config_threshold(selected, report.relative_to(REPO_ROOT), _git_sha())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
