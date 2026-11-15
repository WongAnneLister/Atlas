from __future__ import annotations

import json

import pytest
from eval import gate_round3, sweep
from eval.schema import EvalItem

from support_agent.config import Settings
from support_agent.retrieval.chunking import Chunk


def item(item_id: str, question: str, answerable: bool, split: str = "dev") -> EvalItem:
    return EvalItem(
        id=item_id,
        group="basic_policy" if answerable else "no_answer",
        split=split,  # type: ignore[arg-type]
        question=question,
        gold_sections=["s"] if answerable else [],
        answer_points=["p"] if answerable else [],
        answerable=answerable,
        source="fixture",
        notes=json.dumps({"family": "fam", "closed_list": False}),
    )


def snapshot(item_id: str, answerable: bool, *scores: float) -> sweep.GateScore:
    return sweep.GateScore(
        id=item_id,
        group="basic_policy" if answerable else "no_answer",
        split="dev",
        answerable=answerable,
        score=0.0,
        signals={},
        chunks=[sweep.ChunkScore(chunk_id=f"c{n}", rerank=value) for n, value in enumerate(scores)],
    )


def test_wilson_interval_matches_known_values() -> None:
    low, high = gate_round3.wilson(0, 106)
    assert low == 0.0
    assert high == pytest.approx(0.0349, abs=1e-3)
    with pytest.raises(ValueError):
        gate_round3.wilson(0, 0)


def test_variants_share_snapshots_and_only_v3_vetoes_unlisted_brands(monkeypatch) -> None:
    texts = {
        "c0": "We accept major credit cards, debit cards, and PayPal.",
        "c1": "Returns are accepted within 30 days.",
        "c2": "Gift wrapping costs extra.",
    }
    chunks = {
        cid: Chunk(
            chunk_id=cid,
            doc_id="d",
            section_id=cid,
            title="t",
            heading_path="h",
            text=text,
            n_tokens=3,
        )
        for cid, text in texts.items()
    }
    monkeypatch.setattr(sweep, "load_local_chunks", lambda settings, path=None: chunks)
    items = [
        item("ok", "What payment methods do you accept?", True),
        item("far", "What are the opening hours of your showroom?", False),
        item("near", "Can I use Cash App Pay to pay here?", False, "test"),
    ]
    snapshots = {
        "dev": [snapshot("ok", True, 0.95, 0.4), snapshot("far", False, 0.01, 0.005)],
        "test": [snapshot("near", False, 0.9, 0.2).model_copy(update={"split": "test"})],
        "holdout": [],
    }
    results = [
        gate_round3.evaluate_variant(Settings(), variant, snapshots, items)
        for variant in gate_round3.VARIANTS
    ]
    v0, v3 = results[0], results[-1]
    assert gate_round3.count_false_accepts(v0.test, v0.threshold) == 1
    assert gate_round3.count_false_accepts(v3.test, v3.threshold) == 0
    assert v3.test[0].vetoed
    # V0 adds a free key_hit to the far no-answer item; V1 onwards does not.
    assert v0.dev[1].score >= 0.15
    assert results[1].dev[1].score < 0.02
    assert all(gate_round3.count_false_rejects(r.dev, r.threshold) == 0 for r in results)
