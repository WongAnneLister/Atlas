"""Ask a language model to flag unsupported answer claims for human review."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from eval.e2e_records import E2ERecord, JudgeRecord
from support_agent.config import REPO_ROOT, get_settings
from support_agent.graph.deps import GraphDeps


class JudgeDecision(BaseModel):
    flagged: bool
    claims: list[str] = Field(default_factory=list)


def _records(path: Path) -> list[E2ERecord]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [E2ERecord.model_validate_json(line) for line in lines[1:] if line.strip()]


def judge_record(model: Any, prompt: str, record: E2ERecord) -> JudgeRecord:
    if not record.accepted or not record.cited_sources:
        return JudgeRecord(item_id=record.item.id, flagged=False)
    payload = {
        "answer": record.answer,
        "cited_sources": record.cited_sources,
    }
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
    return JudgeRecord(item_id=record.item.id, flagged=decision.flagged, claims=decision.claims)


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


def write_report(records: list[JudgeRecord], output: Path, provenance: dict[str, str]) -> None:
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
    args = parser.parse_args(argv)
    output = REPO_ROOT / args.output
    run_path = REPO_ROOT / args.run
    if not args.import_csv and not run_path.is_file():
        raise FileNotFoundError(f"End-to-end run not found: {run_path}")
    metadata = (
        json.loads(run_path.read_text(encoding="utf-8").splitlines()[0])
        if run_path.is_file()
        else {
            key: "pending"
            for key in (
                "git_sha",
                "config_hash",
                "eval_file_hash",
                "corpus_hash",
                "split",
                "date",
                "models",
                "dataset_versions",
            )
        }
    )
    if args.import_csv:
        records = import_confirmations(output, REPO_ROOT / args.import_csv)
    else:
        source_records = _records(run_path)
        settings = get_settings()
        prompt_path = REPO_ROOT / "eval/prompts/judge.md"
        with GraphDeps(settings) as deps:
            model = deps.model("main")
            records = [
                judge_record(model, prompt_path.read_text(encoding="utf-8"), record)
                for record in source_records
            ]
    export_csv(records, output)
    write_report(
        records,
        REPO_ROOT / "eval/reports/hallucination_review.md",
        {
            key.replace("_", " ").title(): str(metadata[key])
            for key in (
                "git_sha",
                "config_hash",
                "eval_file_hash",
                "corpus_hash",
                "split",
                "date",
                "models",
                "dataset_versions",
            )
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
