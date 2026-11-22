"""Score saved verifier decisions against human labels and separate synthetic negatives."""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from eval.build_claims import CLAIMS_PATH, NAME, read_claims
from eval.registry import file_hash, load_registry
from eval.schema import CLAIM_PERTURBATIONS, ClaimItem, ClaimVerdict, Split
from eval.stats import Interval, wilson_interval
from support_agent.config import REPO_ROOT, get_settings
from support_agent.data.doc_models import write_text


class Prediction(BaseModel):
    id: str
    verdict: ClaimVerdict


class PredictionRun(BaseModel):
    git_sha: str
    config_hash: str
    dataset_sha256: str
    models: dict[str, str]
    date: str
    split: Split
    predictions: list[Prediction] = Field(min_length=1)


@dataclass(frozen=True)
class ClaimScore:
    total: int
    labelled: int
    tp: int
    fp: int
    fn: int
    precision: Interval | None
    recall: Interval | None
    f1: Interval | None


def _score(total: int, labelled: int, tp: int, fp: int, fn: int, alpha: float) -> ClaimScore:
    precision = wilson_interval(tp, tp + fp, alpha) if tp + fp else None
    recall = wilson_interval(tp, tp + fn, alpha) if tp + fn else None
    f1 = None
    if tp + fp + fn:
        # F1 is a monotone transform of Jaccard. Transform that Wilson interval.
        overlap = wilson_interval(tp, tp + fp + fn, alpha)
        f1 = Interval(
            2 * overlap.point / (1 + overlap.point),
            2 * overlap.low / (1 + overlap.low),
            2 * overlap.high / (1 + overlap.high),
        )
    return ClaimScore(total, labelled, tp, fp, fn, precision, recall, f1)


def score_claims(
    items: list[ClaimItem], predictions: dict[str, ClaimVerdict], *, alpha: float
) -> dict[tuple[Split, str], ClaimScore]:
    ids = {item.id for item in items}
    if len(ids) != len(items) or predictions.keys() - ids:
        raise ValueError("Duplicate claim items or unknown prediction IDs")
    groups: dict[tuple[Split, str], list[ClaimItem]] = defaultdict(list)
    for item in items:
        groups[item.split, item.group].append(item)
        if item.perturbation is not None:
            groups[item.split, f"synthetic / {item.perturbation}"].append(item)
    for split in {item.split for item in items if item.group == "synthetic"}:
        for kind in CLAIM_PERTURBATIONS:
            groups.setdefault((split, f"synthetic / {kind}"), [])
    results = {}
    for key, rows in sorted(groups.items()):
        tp = fp = fn = labelled = 0
        for item in rows:
            # Synthetic negatives are excluded from human review and keep a null label.
            if item.group == "real" and item.label is None:
                continue
            try:
                predicted = predictions[item.id] != "supported"
            except KeyError:
                raise ValueError(f"Missing prediction for labelled claim {item.id}") from None
            unsupported = item.group == "synthetic" or item.label == "unsupported"
            labelled += 1
            tp += int(predicted and unsupported)
            fp += int(predicted and not unsupported)
            fn += int(not predicted and unsupported)
        results[key] = _score(len(rows), labelled, tp, fp, fn, alpha)
    return results


def _format(interval: Interval | None) -> str:
    if interval is None:
        return "n/a"
    return f"{interval.point:.2%} [{interval.low:.2%}, {interval.high:.2%}]"


def render_report(
    run: PredictionRun,
    version: str,
    scores: dict[tuple[Split, str], ClaimScore],
    *,
    target_recall: float,
    alpha: float,
    label_sources: dict[str, int] | None = None,
) -> str:
    models = ", ".join(f"{role}={model}" for role, model in sorted(run.models.items()))
    lines = [
        "# Claim verifier",
        "",
        rf"- Verifier SHA: `{run.git_sha}`",
        rf"- Verifier config hash: `{run.config_hash}`",
        rf"- Dataset: {NAME} {version} (`{run.dataset_sha256}`)",
        f"- Models: {models or 'unavailable'}",
        f"- Run date: {run.date}",
        f"- Eval split: {run.split}",
        f"- Recall target: {target_recall:.2%}",
        f"- Interval level: {1 - alpha:.0%}",
        "",
        "| Split | Group | Scored / total | TP | FP | FN | Precision | Recall | F1 | Target |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |",
    ]
    for (split, group), score in scores.items():
        if score.recall is None:
            target = "n/a"
        else:
            target = "met" if score.recall.point >= target_recall else "below target"
        lines.append(
            f"| {split} | {group} | {score.labelled}/{score.total} | {score.tp} | "
            f"{score.fp} | {score.fn} | {_format(score.precision)} | {_format(score.recall)} | "
            f"{_format(score.f1)} | {target} |"
        )
    lines += [
        "",
        "Partial verdicts count as unsupported. Real claims without a label are excluded.",
        *(
            [
                "Real-claim label sources: "
                + ", ".join(f"{source} {count}" for source, count in sorted(label_sources.items()))
                + ". `model_draft` labels were drafted by a model and not reviewed by the author.",
            ]
            if label_sources
            else []
        ),
        "Synthetic negatives contain no positive support examples, so their precision cannot",
        "measure how often the verifier would reject supported claims.",
        "F1 intervals transform the Wilson interval for TP / (TP + FP + FN).",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        args.predictions.resolve().relative_to(REPO_ROOT)
        run = PredictionRun.model_validate_json(args.predictions.read_bytes())
        entry = load_registry()[NAME]
        if file_hash(CLAIMS_PATH) != entry.sha256 or run.dataset_sha256 != entry.sha256:
            raise ValueError("Prediction run and local claims must match the registered dataset")
        items = [item for item in read_claims() if item.split == run.split]
        predictions = {prediction.id: prediction.verdict for prediction in run.predictions}
        if len(predictions) != len(run.predictions):
            raise ValueError("Duplicate verifier prediction ID")
        settings = get_settings()
        alpha = settings.eval.stats.alpha
        report = render_report(
            run,
            entry.version,
            score_claims(items, predictions, alpha=alpha),
            target_recall=settings.grounding.target_recall,
            alpha=alpha,
            label_sources=dict(
                Counter(
                    item.label_source
                    for item in items
                    if item.group == "real" and item.label is not None
                )
            ),
        )
        if args.report:
            args.report.resolve().relative_to(REPO_ROOT)
            write_text(args.report, report)
        else:
            sys.stdout.write(report)
    except (KeyError, ValueError, OSError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
