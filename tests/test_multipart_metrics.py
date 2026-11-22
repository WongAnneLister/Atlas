"""Offline fixtures for multipart scoring and legacy replay."""

from eval import metrics
from eval.e2e_records import E2ERecord
from eval.schema import EvalItem


def _part(text, *, gold=None):
    return {
        "source_item_id": text,
        "text": text,
        "gold_sections": [gold] if gold else [],
        "answer_points": ["point"] if gold else [],
        "answerable": gold is not None,
    }


def _multipart(group, first_gold=None, second_gold=None, **result):
    return E2ERecord.model_validate(
        {
            "item": {
                "id": "multipart-fixture",
                "group": group,
                "split": "test",
                "question": "Policy returns, and also product care?",
                "source": "fixture",
                "parts": [
                    _part("Policy returns?", gold=first_gold),
                    _part("Product care?", gold=second_gold),
                ],
            },
            "latency_full_answer_s": 1,
            **result,
        }
    )


def _legacy(group, gold, *, accepted=False, cited=(), retrieved=(), parts=None):
    row = {
        "item": {
            "id": "legacy-fixture",
            "group": group,
            "split": "test",
            "question": "Policy returns and product care?",
            "source": "fixture",
            "gold_sections": gold,
            "answer_points": ["point"] if gold else [],
            "answerable": bool(gold),
        },
        "latency_full_answer_s": 1,
        "accepted": accepted,
        "cited_sources": [{"section_id": section} for section in cited],
        "retrieved_section_ids": retrieved,
    }
    if parts is not None:
        row["parts"] = parts
    return E2ERecord.model_validate(row)


def test_legacy_cross_doc_requires_every_gold_citation():
    one = _legacy("cross_doc", ["returns", "care"], accepted=True, cited=["returns"])
    both = _legacy("cross_doc", ["returns", "care"], accepted=True, cited=["returns", "care"])
    assert isinstance(one.item, EvalItem)
    assert one.parts is None
    assert not metrics.full_answer(one)
    assert metrics.full_answer(both)
    assert not metrics.full_answer(both.model_copy(update={"accepted": False}))


def test_part_recall_checks_top_five_per_part_before_combining():
    row = _multipart(
        "answerable_pair",
        "returns",
        "care",
        parts=[
            {
                "text": "Policy returns?",
                "retrieved_section_ids": ["a", "b", "c", "d", "e", "returns"],
            },
            {"text": "Product care?", "retrieved_section_ids": ["care"]},
        ],
        retrieved_section_ids=["returns", "care"],
    )
    assert not metrics.part_recall_at_5(row)
    row.parts[0].retrieved_section_ids[4] = "returns"
    assert metrics.part_recall_at_5(row)
    assert metrics.part_recall_at_5(
        _legacy("cross_doc", ["returns", "care"], retrieved=["returns", "care"])
    )


def test_full_answer_requires_cited_coverage_from_answered_parts():
    row = _multipart(
        "answerable_pair",
        "returns",
        "care",
        accepted=True,
        cited_sources=[{"section_id": "returns"}, {"section_id": "care"}],
        parts=[
            {
                "text": "Policy returns?",
                "answered": True,
                "cited_section_ids": ["returns"],
                "gate": {"passed": True},
            },
            {"text": "Product care?", "answered": False, "cited_section_ids": ["care"]},
        ],
    )
    assert not metrics.full_answer(row)
    row.parts[1].answered = True
    assert metrics.full_answer(row)
    assert E2ERecord.model_validate_json(row.model_dump_json()) == row
    merged = row.model_copy(deep=True)
    merged.parts[0].cited_section_ids.append("care")
    merged.parts.pop()
    assert not metrics.full_answer(merged)
    row.parts[0].cited_section_ids, row.parts[1].cited_section_ids = (
        row.parts[1].cited_section_ids,
        row.parts[0].cited_section_ids,
    )
    assert not metrics.full_answer(row)


def test_no_answer_counts_any_answered_part_even_when_handed_off():
    legacy = _legacy("no_answer", [], parts=[{"text": "Policy returns?", "answered": True}])
    leaked = _multipart(
        "both_unanswerable",
        handoff_reason="incomplete_evidence",
        parts=[{"text": "Policy returns?", "answered": True}],
    )
    safe = _multipart("both_unanswerable", handoff_reason="incomplete_evidence")
    assert not leaked.accepted
    assert metrics.noanswer_false_accept(legacy)
    assert metrics.noanswer_false_accept(leaked)
    assert metrics.noanswer_false_accept(_legacy("no_answer", [], accepted=True))
    assert not metrics.noanswer_false_accept(safe)
    assert metrics.part_metric_values(legacy) == {"noanswer_false_accept": True}
    assert metrics.part_metric_values(leaked) == {
        "partial_answer_rate": True,
        "noanswer_false_accept": True,
    }


def test_half_answerable_distinguishes_targeted_handoff_and_whole_handoff():
    mixed = _multipart(
        "half_answerable",
        "returns",
        handoff_reason="incomplete_evidence",
        parts=[
            {"text": "Policy returns?", "answered": True, "cited_section_ids": ["returns"]},
            {"text": "PRODUCT care", "handed_off": True},
        ],
    )
    complete_handoff = _multipart("half_answerable", "returns", handoff_reason="low_evidence")
    wrong_handoff = mixed.model_copy(deep=True)
    wrong_handoff.parts[1].text = "Payment options"
    assert metrics.partial_answer(mixed)
    assert metrics.answered_part_correct(mixed)
    assert metrics.unanswerable_part_handed_off(mixed)
    assert not metrics.unanswerable_part_handed_off(wrong_handoff)
    assert not metrics.partial_answer(complete_handoff)
    assert not metrics.answered_part_correct(complete_handoff)
    assert metrics.unanswerable_part_handed_off(complete_handoff)
    assert metrics.part_metric_values(mixed) == {
        "partial_answer_rate": True,
        "part_recall_at_5": False,
        "answered_part_correct": True,
        "unanswerable_part_handed_off": True,
    }
    wrong_handoff.parts[0].text = "Product care?"
    assert not metrics.answered_part_correct(wrong_handoff)
