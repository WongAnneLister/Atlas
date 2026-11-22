"""Ask a language model to flag unsupported answer claims for human review."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from eval.e2e_records import E2EMetadata, E2ERecord, JudgeRecord
from eval.e2e_runs import load_e2e
from eval.judge_calibration import audit_key, read_kappa
from eval.run_record import (
    RUNS,
    RunItem,
    RunManifest,
    confidence_level,
    dataset_version,
    format_summary,
    git,
    is_dirty,
    read_run,
    write_run,
)
from support_agent.config import REPO_ROOT, get_settings
from support_agent.data.doc_models import digest, json_text, write_text
from support_agent.graph.deps import GraphDeps
from support_agent.llm import resolve_model


class JudgeDecision(BaseModel):
    flagged: bool
    claims: list[str] = Field(default_factory=list)


def judge_record(model: Any, prompt: str, record: E2ERecord) -> JudgeRecord:
    if not record.accepted or not record.cited_sources:
        return JudgeRecord(item_id=record.item.id, flagged=False)
    return _judge(
        model,
        prompt,
        record.item.id,
        {
            "answer": record.answer,
            "cited_sources": record.cited_sources,
        },
    )


def partial_payload(record: E2ERecord) -> dict[str, Any]:
    return {
        "question": record.item.question,
        "answer": record.answer,
        "cited_sources": record.cited_sources,
        "parts": [part.model_dump(mode="json") for part in record.parts or []],
    }


def judge_partial_record(model: Any, prompt: str, record: E2ERecord) -> JudgeRecord:
    return _judge(model, prompt, record.item.id, partial_payload(record))


def _judge(model: Any, prompt: str, item_id: str, payload: dict[str, Any]) -> JudgeRecord:
    response = model.invoke(
        [
            SystemMessage(content=prompt),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
        ]
    )
    content = getattr(response, "content", "")
    if not isinstance(content, str):
        raise ValueError("Judge returned no text")
    decision = JudgeDecision.model_validate_json(content)
    return JudgeRecord(item_id=item_id, flagged=decision.flagged, claims=decision.claims)


def export_csv(records: list[JudgeRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["item_id", "flagged", "claims", "confirmed"])
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "item_id": record.item_id,
                    "flagged": str(record.flagged).lower(),
                    "claims": json.dumps(record.claims, ensure_ascii=False),
                    "confirmed": record.confirmed,
                }
            )


def import_confirmations(path: Path, confirmations_path: Path) -> list[JudgeRecord]:
    with confirmations_path.open(encoding="utf-8", newline="") as stream:
        confirmations = {
            row["item_id"]: row["confirmed"].strip().lower() for row in csv.DictReader(stream)
        }
    rows: list[JudgeRecord] = []
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            confirmed = confirmations.get(row["item_id"], row.get("confirmed", ""))
            if confirmed not in {"", "yes", "no"}:
                raise ValueError(f"Invalid confirmation for {row['item_id']}")
            rows.append(
                JudgeRecord(
                    item_id=row["item_id"],
                    flagged=row["flagged"].strip().lower() == "true",
                    claims=json.loads(row["claims"]),
                    confirmed=confirmed,
                )
            )
    return rows


def read_review(path: Path) -> list[JudgeRecord]:
    return import_confirmations(path, path)


def project_judge(records: list[JudgeRecord]) -> list[RunItem]:
    return [
        RunItem(
            id=row.item_id,
            metrics={
                "judge_flagged": row.flagged,
                **({"human_confirmed": row.confirmed == "yes"} if row.confirmed else {}),
            },
            payload=row.model_dump(mode="json"),
        )
        for row in records
    ]


def save_judge(
    records: list[JudgeRecord],
    metadata: E2EMetadata,
    *,
    root: Path = RUNS,
    suffix: str | None = None,
    started_at: datetime | None = None,
    dirty: bool | None = None,
    command: list[str] | None = None,
) -> Path:
    settings = get_settings()
    model, _ = resolve_model("main", settings.llm) if started_at else (None, None)
    source = metadata.model_dump(mode="json")
    source["audit_fingerprint"] = audit_key(metadata, records)
    manifest = RunManifest(
        kind="judge",
        split=metadata.split,
        git_sha=git("rev-parse", "HEAD") if started_at else metadata.git_sha,
        config_hash=digest(json_text(settings.model_dump(mode="json")))
        if started_at
        else metadata.config_hash,
        models={"judge": model} if model else metadata.models,
        datasets=dataset_version(metadata.eval_file_hash),
        seed=settings.eval.stats.seed,
        dirty=dirty,
        started_at=started_at,
        ended_at=datetime.now(UTC) if started_at else None,
        cost_usd=None,
        cost_note="usage not stored"
        if any(
            price.input_per_million_usd is not None and price.output_per_million_usd is not None
            for price in settings.costs.prices.values()
        )
        else "price not set",
        command=command or [],
        source=source,
    )
    return write_run(manifest, project_judge(records), root=root, suffix=suffix)


def render_judge(run_path: Path, report: Path) -> None:
    run = read_run(run_path)
    if run.manifest.kind != "judge":
        raise ValueError("Expected a judge run")
    records = [JudgeRecord.model_validate(row.payload) for row in run.items]
    metadata = E2EMetadata.model_validate(run.manifest.source).model_dump(mode="json")
    keys = (
        "git_sha",
        "config_hash",
        "eval_file_hash",
        "corpus_hash",
        "split",
        "date",
        "models",
        "dataset_versions",
    )
    provenance = {key.replace("_", " ").title(): str(metadata[key]) for key in keys}
    if run.manifest.started_at:
        provenance.update(
            {
                "Judge run Git SHA": run.manifest.git_sha,
                "Judge run config hash": run.manifest.config_hash,
                "Judge run start (UTC)": run.manifest.started_at.isoformat(),
                "Judge run models": str(run.manifest.models),
            }
        )
    kappa = read_kappa(audit=run.manifest.source.get("audit_fingerprint"))
    write_report(records, report, provenance, kappa=kappa)
    confidence = confidence_level(run.metrics)
    lines = [
        "",
        "## Confidence intervals",
        "",
        f"| Metric | Estimate and {confidence:.0%} CI |",
        "|---|---|",
    ]
    for name, summary in run.metrics.metrics.items():
        label = f"{name} ({kappa})" if name == "judge_flagged" else name
        lines.append(f"| {label} | {format_summary(summary)} |")
    write_text(report, report.read_text(encoding="utf-8") + "\n".join(lines) + "\n")


def write_report(
    records: list[JudgeRecord],
    output: Path,
    provenance: dict[str, str],
    *,
    kappa: str | None = None,
) -> None:
    confirmed = [record for record in records if record.confirmed]
    confirmed_rate = (
        sum(record.confirmed == "yes" for record in confirmed) / len(confirmed)
        if confirmed
        else None
    )
    header = ["# Hallucination review", ""]
    header.extend(f"- {key}: `{value}`" for key, value in provenance.items())
    output.write_text(
        "\n".join(
            [
                *header,
                f"- Evaluation rows (including skipped rows): {len(records)}",
                f"- Judge-flagged rate (all evaluation rows): "
                f"{sum(r.flagged for r in records) / len(records):.2%}"
                if records
                else "- Judge-flagged rate: pending",
                f"- Judge calibration: {kappa or read_kappa()}",
                f"- Human-confirmed rate: {confirmed_rate:.2%}"
                if confirmed_rate is not None
                else "- Human-confirmed rate: pending",
                f"- Human confirmations: {len(confirmed)}/{len(records)}",
                "",
                "The judge is a review aid. Human confirmation remains the final label.",
                "Only accepted answers with cited source text receive a model audit.",
                "Other rows are skipped, not verified as supported.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, nargs="?", default=Path("eval/runs/e2e_test.jsonl"))
    parser.add_argument("--import-csv", type=Path)
    parser.add_argument("--output", type=Path, default=Path("eval/sets/hallucination_review.csv"))
    parser.add_argument("--run-dir", type=Path, help="render a saved judge run without models")
    parser.add_argument("--report", type=Path, default=Path("eval/reports/hallucination_review.md"))
    args = parser.parse_args(argv)
    report = REPO_ROOT / args.report
    if args.run_dir:
        render_judge(REPO_ROOT / args.run_dir, report)
        return 0
    output = REPO_ROOT / args.output
    run_path = REPO_ROOT / args.run
    if args.import_csv and not run_path.exists():
        metadata = E2EMetadata(
            git_sha="pending",
            config_hash="pending",
            eval_file_hash="pending",
            corpus_hash="pending",
            split="test",
            date="pending",
            models={},
            dataset_versions={},
            customer_id="pending",
            threshold=0,
        )
        source_records = []
    else:
        metadata, source_records = load_e2e(run_path)
    started_at = None
    dirty = None
    if args.import_csv:
        records = import_confirmations(output, REPO_ROOT / args.import_csv)
    else:
        settings = get_settings()
        prompt = (REPO_ROOT / "eval/prompts/judge.md").read_text(encoding="utf-8")
        started_at = datetime.now(UTC)
        dirty = is_dirty()
        with GraphDeps(settings) as deps:
            model = deps.model("main")
            records = [judge_record(model, prompt, record) for record in source_records]
    export_csv(records, output)
    run = save_judge(
        records,
        metadata,
        root=RUNS,
        suffix=uuid4().hex[:8],
        started_at=started_at,
        dirty=dirty,
        command=["eval-judge", *(argv if argv is not None else sys.argv[1:])],
    )
    render_judge(run, report)
    sys.stdout.write(f"Run record: {run}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
