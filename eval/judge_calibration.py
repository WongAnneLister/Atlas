"""Measure judge agreement on human-confirmed audits without calling a model."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory

import numpy as np
from numpy.typing import NDArray

from eval.e2e_records import E2EMetadata, JudgeRecord
from eval.e2e_runs import load_e2e
from eval.stats import Interval, bootstrap_ci, cohens_kappa
from support_agent.config import REPO_ROOT, get_settings
from support_agent.data.doc_models import digest, json_text, write_text

MIN_HUMAN_LABELS = 30
REPORT_PATH = REPO_ROOT / "eval/reports/judge_calibration.md"
KAPPA_PREFIX = "- Judge status: "


@dataclass(frozen=True)
class Calibration:
    label_count: int
    precision: Interval | None = None
    recall: Interval | None = None
    kappa: Interval | None = None


def select_sample(
    rows: list[JudgeRecord], audited: set[str], *, seed: int, unflagged: int
) -> list[str]:
    flagged = sorted(row.item_id for row in rows if row.item_id in audited and row.flagged)
    negatives = sorted(row.item_id for row in rows if row.item_id in audited and not row.flagged)
    return flagged + sorted(Random(seed).sample(negatives, min(unflagged, len(negatives))))


def calibrate(
    rows: list[JudgeRecord], *, n_resamples: int = 2000, seed: int = 17, alpha: float = 0.05
) -> Calibration:
    labelled = [row for row in rows if row.confirmed]
    if len(labelled) < MIN_HUMAN_LABELS:
        return Calibration(label_count=len(labelled))
    predicted = [row.confirmed == "yes" for row in labelled if row.flagged]
    actual = [row.flagged for row in labelled if row.confirmed == "yes"]
    codes = np.asarray(
        [2 * (not row.flagged) + (row.confirmed == "no") for row in labelled],
        dtype=float,
    )
    options = {"n_resamples": n_resamples, "seed": seed, "alpha": alpha}
    return Calibration(
        label_count=len(labelled),
        precision=bootstrap_ci(predicted, **options) if predicted else None,
        recall=bootstrap_ci(actual, **options) if actual else None,
        kappa=bootstrap_ci(codes, stat=_kappa, **options) if np.isfinite(_kappa(codes)) else None,
    )


def _kappa(codes: NDArray[np.float64]) -> float:
    tp, fp, fn, tn = np.bincount(codes.astype(int), minlength=4).tolist()
    value = cohens_kappa(((tp, fp), (fn, tn)))
    return value if value is not None else float("nan")


def _status(result: Calibration) -> str:
    if result.label_count < MIN_HUMAN_LABELS:
        return f"kappa: n/a ({result.label_count}/{MIN_HUMAN_LABELS} labels)"
    if result.kappa is None:
        return f"kappa: n/a ({result.label_count} labels, undefined)"
    return f"kappa: {result.kappa.point:.3f} ({result.label_count} labels)"


def audit_key(metadata: E2EMetadata, rows: list[JudgeRecord]) -> str:
    predictions = sorted(rows, key=lambda row: row.item_id)
    return digest(
        json_text(
            {
                "run": metadata.model_dump(mode="json"),
                "predictions": [
                    row.model_dump(mode="json", exclude={"confirmed"}) for row in predictions
                ],
            }
        )
    )


def read_kappa(report: Path = REPORT_PATH, *, audit: str | None = None) -> str:
    if report.is_file():
        lines = report.read_text(encoding="utf-8").splitlines()
        if audit is not None and f"- Audit fingerprint: `{audit}`" not in lines:
            return "kappa: n/a (no calibration for this audit)"
        for line in lines:
            if line.startswith(KAPPA_PREFIX):
                return line.removeprefix(KAPPA_PREFIX)
    return "kappa: n/a (calibration report unavailable)"


def render_report(result: Calibration, provenance: dict[str, str], alpha: float = 0.05) -> str:
    lines = [
        "# Judge calibration",
        "",
        *[f"- {key}: `{value}`" for key, value in provenance.items()],
        f"- Audited rows with human labels: {result.label_count}",
        KAPPA_PREFIX + _status(result),
        "",
    ]
    if result.label_count < MIN_HUMAN_LABELS:
        lines.append(
            f"{MIN_HUMAN_LABELS - result.label_count} more human labels are needed "
            f"to reach {MIN_HUMAN_LABELS}."
        )
    else:
        lines.extend(
            [
                f"| Measure | Estimate | {(1 - alpha):.0%} CI |",
                "|---|---:|---:|",
            ]
        )
        for name, metric in (
            ("Precision", result.precision),
            ("Recall", result.recall),
            ("Cohen's kappa", result.kappa),
        ):
            lines.append(
                f"| {name} | {metric.point:.3f} | [{metric.low:.3f}, {metric.high:.3f}] |"
                if metric is not None
                else f"| {name} | undefined | — |"
            )
    lines.extend(
        [
            "",
            "The review sample includes every judge flag and a seeded sample of audited unflagged "
            "answers. Skipped rows are excluded. Estimates describe the labelled sample. "
            "Oversampling flags can shift recall and kappa relative to the full audit set.",
            "Bootstrap intervals use the labelled rows. Kappa intervals omit draws with undefined "
            "agreement.",
            "",
        ]
    )
    return "\n".join(lines)


def _load_review(path: Path) -> list[JudgeRecord]:
    with path.open(encoding="utf-8", newline="") as stream:
        rows: list[JudgeRecord] = []
        for row in csv.DictReader(stream):
            prediction = row["flagged"].strip().lower()
            if prediction not in {"true", "false"}:
                raise ValueError(f"Invalid judge flag for {row['item_id']}")
            rows.append(
                JudgeRecord(
                    item_id=row["item_id"],
                    flagged=prediction == "true",
                    claims=json.loads(row["claims"]),
                    confirmed=row["confirmed"].strip().lower(),
                )
            )
    if len({row.item_id for row in rows}) != len(rows):
        raise ValueError("Duplicate judge review IDs")
    return rows


def _update_sample(
    path: Path, sample: list[str], rows: dict[str, dict[str, str]]
) -> dict[str, str]:
    labels: dict[str, str] = {}
    if path.exists():
        with path.open(encoding="utf-8", newline="") as stream:
            for existing in csv.DictReader(stream):
                label = existing["human_label"].strip().lower()
                if not label:
                    continue
                item_id = existing["item_id"]
                if label not in {"yes", "no"} or item_id in labels:
                    raise ValueError(f"Invalid or duplicate human label for {item_id}")
                current = rows.get(item_id)
                if current is None or any(
                    existing.get(key) != value for key, value in current.items()
                ):
                    raise ValueError(
                        f"Stale calibration sample label for {item_id}; use a new sample"
                    )
                labels[item_id] = label
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["item_id", "question", "answer", "cited_sources", "flagged", "claims", "human_label"]
    with TemporaryDirectory(dir=path.parent) as directory:
        temporary = Path(directory) / path.name
        with temporary.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for item_id in dict.fromkeys([*sample, *labels]):
                writer.writerow({**rows[item_id], "human_label": labels.get(item_id, "")})
        temporary.replace(path)
    return labels


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--review", type=Path, default=Path("eval/sets/baseline-001-hallucination-review.csv")
    )
    parser.add_argument("--run", type=Path, default=Path("eval/runs/baseline-001-e2e-test.jsonl"))
    parser.add_argument("--sample", type=Path, default=Path("eval/sets/judge_calibration.csv"))
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    args = parser.parse_args(argv)

    review = _load_review(REPO_ROOT / args.review)
    meta, records = load_e2e(REPO_ROOT / args.run)
    fingerprint = audit_key(meta, review)
    indexed = {row.item.id: row for row in records}
    if len(indexed) != len(records) or indexed.keys() != {row.item_id for row in review}:
        raise ValueError("Review and source run must contain the same unique item IDs")
    audited = {row.item.id for row in records if row.accepted and row.cited_sources}
    if any(row.flagged and row.item_id not in audited for row in review):
        raise ValueError("Judge review flags an item that was skipped in the supplied run")
    review = [row for row in review if row.item_id in audited]
    rows = {}
    for row in review:
        record = indexed[row.item_id]
        rows[row.item_id] = {
            "item_id": row.item_id,
            "question": record.item.question,
            "answer": record.answer,
            "cited_sources": json.dumps(record.cited_sources, ensure_ascii=False),
            "flagged": str(row.flagged).lower(),
            "claims": json.dumps(row.claims, ensure_ascii=False),
        }

    settings = get_settings().eval.stats
    sample = select_sample(review, audited, seed=settings.seed, unflagged=MIN_HUMAN_LABELS)
    labels = _update_sample(REPO_ROOT / args.sample, sample, rows)
    for row in review:
        label = labels.get(row.item_id)
        if label and row.confirmed and row.confirmed != label:
            raise ValueError(f"Conflicting human labels for {row.item_id}")
        if label:
            row.confirmed = "yes" if label == "yes" else "no"
    result = calibrate(
        review, n_resamples=settings.n_resamples, seed=settings.seed, alpha=settings.alpha
    )
    provenance = {
        "Audit fingerprint": fingerprint,
        "Source run SHA": meta.git_sha,
        "Source run config hash": meta.config_hash,
        "Source run models": json.dumps(meta.models, sort_keys=True),
        "Dataset versions": json.dumps(meta.dataset_versions, sort_keys=True),
        "Source eval file hash": meta.eval_file_hash,
        "Split": meta.split,
        "Source run date": meta.date,
        "Seed": str(settings.seed),
        "Bootstrap resamples": str(settings.n_resamples),
    }
    write_text(REPO_ROOT / args.output, render_report(result, provenance, alpha=settings.alpha))
    sys.stdout.write(_status(result) + "\n")
    if result.label_count < MIN_HUMAN_LABELS:
        sys.stdout.write(f"{MIN_HUMAN_LABELS - result.label_count} more human labels are needed.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
