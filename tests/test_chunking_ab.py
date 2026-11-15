from __future__ import annotations

import json

from eval import chunking_ab
from eval.schema import EvalItem
from eval.sweep import ChunkScore, GateScore

from support_agent.retrieval.chunking import Chunk


def item(notes: str = "", points: list[str] | None = None) -> EvalItem:
    return EvalItem(
        id="i",
        group="basic_policy",
        split="test",
        question="q",
        gold_sections=["s"],
        answer_points=points or ["We accept credit cards and PayPal."],
        answerable=True,
        source="fixture",
        notes=notes,
    )


def chunk(cid: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=cid, doc_id="d", section_id="s", title="t", heading_path="h", text=text, n_tokens=5
    )


def record(*ids: str) -> GateScore:
    return GateScore(
        id="i",
        group="basic_policy",
        split="test",
        answerable=True,
        score=0.5,
        signals={},
        chunks=[ChunkScore(chunk_id=c, rerank=0.5) for c in ids],
    )


def test_evidence_uses_notes_anchor_or_answer_start() -> None:
    assert chunking_ab.evidence_strings(item(json.dumps({"evidence": "anchor"}))) == ["anchor"]
    assert chunking_ab.evidence_strings(item()) == ["We accept credit cards and PayPal."]


def test_evidence_hit_ignores_whitespace_and_needs_every_point() -> None:
    texts = {"a": chunk("a", "We  accept\ncredit cards and PayPal."), "b": chunk("b", "other")}
    assert chunking_ab.evidence_hit(item(), record("b", "a"), texts)
    assert not chunking_ab.evidence_hit(item(), record("b"), texts)
    two = item(points=["We accept credit cards", "Refunds take 7 days"])
    assert not chunking_ab.evidence_hit(two, record("a"), texts)
