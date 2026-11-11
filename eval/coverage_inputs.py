"""Freeze controlled passages and existing retrieval dev contexts before inference."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel

from eval.retrieval_records import RetrievalRun
from support_agent.data.doc_models import digest, write_text
from support_agent.retrieval.types import RetrievedChunk


class CoverageCase(BaseModel):
    id: str
    split: Literal["dev", "test"]
    subset: Literal["controls", "retrieval_dev"]
    scenario: str
    question: str
    complete: bool
    chunks: list[RetrievedChunk]


def load_inputs(path: Path, split: str) -> tuple[dict[str, Any], list[CoverageCase]]:
    lines = path.read_text().splitlines()
    meta = json.loads(lines[0])
    items = [CoverageCase.model_validate_json(line) for line in lines[1:]]
    if len({i.id for i in items}) != len(items):
        raise ValueError("Coverage inputs contain duplicate ids")
    return meta, [i for i in items if i.split == split]


def freeze_inputs(retrieval_path: Path, controls_path: Path, output: Path) -> None:
    if output.exists():
        raise ValueError("Coverage inputs already frozen; choose a fresh path")
    run = RetrievalRun.model_validate_json(retrieval_path.read_text())
    cases = [
        CoverageCase(
            id=r.item.id,
            split="dev",
            subset="retrieval_dev",
            scenario=r.item.group,
            question=r.item.question,
            complete=True,
            chunks=r.chunks,
        )
        for r in run.records
        if r.mode == "hybrid_rerank" and r.item.split == "dev"
    ]
    for row in yaml.safe_load(controls_path.read_text()):
        sources = row.pop("sources")
        chunks = [
            RetrievedChunk(
                chunk_id=f"{row['id']}-{n}",
                doc_id=row["id"],
                section_id=f"{row['id']}.source{n}",
                title="Store reference",
                heading_path="Store reference",
                text=text,
                n_tokens=len(text.split()),
                scores={"rerank": 0.99},
            )
            for n, text in enumerate(sources, 1)
        ]
        cases.append(CoverageCase(**row, subset="controls", chunks=chunks))
    if len({i.id for i in cases}) != len(cases):
        raise ValueError("Coverage inputs contain duplicate ids")
    meta = {
        "retrieval_input_hash": digest(retrieval_path.read_text()),
        "retrieval_metadata": run.metadata.model_dump(mode="json"),
        "controls_hash": digest(controls_path.read_text()),
        "label_status": "Authored controls; original dev labels unreviewed. No human review.",
        "scope": "Answer stage with fixed contexts, not full-graph or live retrieval performance.",
    }
    write_text(output, json.dumps(meta) + "\n" + "".join(i.model_dump_json() + "\n" for i in cases))
