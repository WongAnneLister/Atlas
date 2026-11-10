"""Sweep the evidence gate on cached dev scores and report held-out test results."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from eval.common import load_items
from eval.metrics import Rates, sweep_rates
from eval.schema import EvalItem
from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.data.doc_models import digest, json_text, write_text
from support_agent.gate.evidence import evaluate
from support_agent.retrieval.embed import BgeM3Embedder
from support_agent.retrieval.factory import build_retriever
from support_agent.retrieval.milvus_store import MilvusStore
from support_agent.retrieval.rerank import BgeReranker


class GateScore(BaseModel):
    record_type: str = "item"
    id: str
    group: str
    split: str
    answerable: bool
    score: float = Field(ge=0, le=1)
    signals: dict[str, float]
    ranked_section_ids: list[str] = Field(default_factory=list)


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


def rates_for_records(records: list[GateScore], threshold: float) -> Rates:
    return sweep_rates(
        [record.answerable for record in records],
        [record.score for record in records],
        threshold,
    )


def select_threshold(records: list[GateScore]) -> float | None:
    """Pick the lowest configured threshold with zero dev false accepts."""
    for threshold in thresholds():
        if rates_for_records(records, threshold).false_accept == 0:
            return threshold
    return None


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
    score_settings = settings.model_copy(deep=True)
    score_settings.gate.threshold = None
    return digest(json_text(score_settings.model_dump(mode="json")))


def collect_scores(settings: Settings, split: str, output: Path) -> list[GateScore]:
    """Run retrieval once per question and cache only gate inputs and scores."""
    eval_path, items, corpus_hash = _eval_paths(settings, split)
    if not items:
        raise ValueError(f"No {split} evaluation items found")
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
        records = []
        for item in items:
            chunks = retriever.retrieve(item.question, settings.retrieval.rerank_top_k)
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
                )
            )
    finally:
        store.close()
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
    write_text(
        output,
        "".join(
            [metadata.model_dump_json() + "\n", *[r.model_dump_json() + "\n" for r in records]]
        ),
    )
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
) -> None:
    highest_no_answer = max((record.score for record in dev if not record.answerable), default=0.0)
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev-cache", type=Path, default=Path("eval/runs/gate_scores_dev.jsonl"))
    parser.add_argument("--test-cache", type=Path, default=Path("eval/runs/gate_scores_test.jsonl"))
    parser.add_argument("--no-collect", action="store_true")
    args = parser.parse_args(argv)
    settings = get_settings().model_copy(deep=True)
    dev_cache = REPO_ROOT / args.dev_cache
    test_cache = REPO_ROOT / args.test_cache
    eval_path, _, corpus_hash = _eval_paths(settings, "dev")
    expected_eval_hash = digest(eval_path.read_text(encoding="utf-8"))

    def cache_matches(path: Path, split: str) -> bool:
        if not path.exists():
            return False
        try:
            metadata, _ = load_scores(path)
        except (OSError, ValueError):
            return False
        return (
            metadata.split == split
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
    dev_meta, dev = load_scores(dev_cache)
    if args.no_collect and not cache_matches(test_cache, "test"):
        test_meta, test = None, None
    else:
        test_meta, test = load_scores(test_cache) if test_cache.exists() else (None, None)
    selected = select_threshold(dev)
    report = REPO_ROOT / "eval/reports/threshold_sweep.md"
    write_report(dev_meta, dev, selected, test_meta, test, report)
    write_plot(dev, REPO_ROOT / "eval/reports/threshold_sweep.png", selected)
    if test is not None:
        _write_config_threshold(selected, report.relative_to(REPO_ROOT), _git_sha())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
