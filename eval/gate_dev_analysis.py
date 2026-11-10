"""Measure evidence-gate signal distributions on the frozen dev split."""

from __future__ import annotations

import json
import logging
import subprocess
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median

import matplotlib.pyplot as plt

from eval.common import load_items
from support_agent.config import REPO_ROOT, get_settings
from support_agent.data.doc_models import digest, json_text, write_text
from support_agent.gate.evidence import evaluate
from support_agent.retrieval.embed import BgeM3Embedder
from support_agent.retrieval.factory import build_retriever
from support_agent.retrieval.milvus_store import MilvusStore
from support_agent.retrieval.rerank import BgeReranker

log = logging.getLogger(__name__)
SIGNALS = ("top_score", "good_count", "margin", "key_hit")


def _summary(values: list[float]) -> tuple[float, float, float]:
    ordered = sorted(values)
    p90 = ordered[min(len(ordered) - 1, int(0.9 * (len(ordered) - 1)))]
    return mean(values), median(values), p90


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = get_settings().model_copy(deep=True)
    eval_file = REPO_ROOT / settings.evaluation.sets_dir / "eval_v1.jsonl"
    manifest = json.loads((eval_file.parent / "manifest.json").read_text(encoding="utf-8"))
    items = [item for item in load_items(eval_file) if item.split == "dev"]
    if not items or any(item.split != "dev" for item in items):
        raise ValueError("Gate analysis requires the frozen dev split only")
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
        groups: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for index, item in enumerate(items, start=1):
            chunks = retriever.retrieve(item.question, settings.retrieval.rerank_top_k)
            result = evaluate(
                item.question,
                chunks,
                settings.gate,
                allow_untuned=True,
            )
            key = (item.group, "answerable" if item.answerable else "no_answer")
            for name, value in {**result.signals, "score": result.score}.items():
                groups[key][name].append(value)
            log.info("dev %d/%d %s", index, len(items), item.id)
        rows = [(group, label, values) for (group, label), values in sorted(groups.items())]
        lines = [
            "# Evidence Gate Signal Analysis (Dev)",
            "",
            "This analysis does not choose a threshold. It uses dev questions only.",
            "No-answer questions are retrieved and reranked with the same settings.",
            "A query without configured key terms gets key_hit = 1.0, a neutral value.",
            "",
            f"- Date: {datetime.now(UTC).date().isoformat()}",
            "- Git SHA: "
            + subprocess.check_output(
                [
                    "git",
                    "-c",
                    f"safe.directory={REPO_ROOT}",
                    "rev-parse",
                    "HEAD",
                ],
                cwd=REPO_ROOT,
                text=True,
            ).strip(),
            f"- Config hash: `{digest(json_text(settings.model_dump(mode='json')))}`",
            f"- Corpus hash: `{manifest['corpus_hash']}`",
            f"- Split: dev ({len(items)} questions)",
            f"- Models: {settings.retrieval.embedding_model} / {settings.retrieval.reranker_model}",
            "- Dataset versions:",
            *[
                f"  - {name}: `{version}`"
                for name, version in sorted(manifest["dataset_versions"].items())
            ],
            "",
            "Values show mean, median, and p90 within each group and answerability label.",
            "",
            "| Group | Label | N | Signal | Mean | Median | P90 |",
            "|---|---|---:|---|---:|---:|---:|",
        ]
        for group, label, values in rows:
            for signal in (*SIGNALS, "score"):
                data = values[signal]
                avg, middle, p90 = _summary(data)
                lines.append(
                    f"| {group} | {label} | {len(data)} | {signal} | "
                    f"{avg:.4f} | {middle:.4f} | {p90:.4f} |"
                )
        report = REPO_ROOT / "eval/reports/gate_signals_dev.md"
        write_text(report, "\n".join(lines) + "\n")
        _plot(rows, REPO_ROOT / "eval/reports/gate_signals_dev.png")
    finally:
        store.close()
    return 0


def _plot(
    rows: list[tuple[str, str, dict[str, list[float]]]],
    path: Path,
) -> None:
    fig, axes = plt.subplots(1, len(SIGNALS) + 1, figsize=(16, 4.5), constrained_layout=True)
    colours = {
        "basic_policy": "#187f78",
        "model_number": "#567fbd",
        "colloquial": "#b88323",
        "cross_doc": "#7866a8",
        "no_answer": "#d56a42",
    }
    for axis, signal in zip(axes, (*SIGNALS, "score"), strict=True):
        for group, label, values in rows:
            axis.hist(
                values[signal],
                bins=12,
                range=(0, 1),
                alpha=0.55,
                color=colours[group],
                label=f"{group} / {label}",
            )
        axis.set_title(signal.replace("_", " "))
        axis.set_xlim(0, 1)
        axis.set_xlabel("Score")
        axis.set_ylabel("Questions")
        axis.grid(axis="y", alpha=0.2)
    handles, labels = axes[0].get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, loc="outside lower center", ncol=3, fontsize=7)
    fig.suptitle("Evidence signals on the dev split")
    fig.savefig(path, dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    raise SystemExit(main())
