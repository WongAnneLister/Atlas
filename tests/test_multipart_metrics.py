"""Offline fixtures for multipart scoring and legacy replay."""

from eval import metrics
from eval.e2e_records import E2ERecord
from eval.schema import EvalItem

from support_agent.config import get_settings


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
    wrong_handoff.parts.append(wrong_handoff.parts[1].model_copy(update={"text": "Gift cards"}))
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


def test_full_answer_aligns_equal_counts_by_position_after_prefix_and_connector_are_dropped():
    row = _multipart(
        "answerable_pair",
        "returns",
        "care",
        accepted=True,
        parts=[
            {"text": "Returns?", "answered": True, "cited_section_ids": ["returns"]},
            {"text": "Product care?", "answered": True, "cited_section_ids": ["care"]},
        ],
    )
    row.item.parts[0].text = "Hi, can you explain policy returns?"
    row.item.parts[1].text = "And also, what about product care?"
    assert metrics.full_answer(row)


def test_half_answerable_scores_by_gold_order_when_unanswerable_part_is_first():
    row = _multipart(
        "half_answerable",
        None,
        "care",
        handoff_reason="incomplete_evidence",
        parts=[
            {"text": "Returns?", "handed_off": True},
            {"text": "Care?", "answered": True, "cited_section_ids": ["care"]},
        ],
    )
    assert metrics.answered_part_correct(row)
    assert metrics.unanswerable_part_handed_off(row)


def test_part_alignment_uses_overlap_for_reordered_parts_with_different_counts(monkeypatch):
    row = _multipart(
        "half_answerable",
        "returns",
        handoff_reason="incomplete_evidence",
        parts=[
            {"text": "Product care details?", "handed_off": True},
            {"text": "Returns?", "answered": True, "cited_section_ids": ["returns"]},
            {"text": "Payment options?"},
        ],
    )
    assert metrics.answered_part_correct(row)
    assert metrics.unanswerable_part_handed_off(row)

    monkeypatch.setattr(get_settings().eval, "multipart_min_overlap", 0.75)
    assert not metrics.answered_part_correct(row)
    assert not metrics.unanswerable_part_handed_off(row)


def test_uneven_full_answer_uses_best_one_to_one_assignment():
    row = _multipart(
        "answerable_pair",
        "returns",
        "care",
        accepted=True,
        parts=[
            {"text": "Returns care", "answered": True, "cited_section_ids": ["care"]},
            {"text": "Payment options", "answered": True, "cited_section_ids": ["other"]},
            {"text": "Returns policy shipping", "answered": True, "cited_section_ids": ["returns"]},
        ],
    )
    row.item.parts[0].text = "Returns policy care"
    row.item.parts[1].text = "Product care"
    assert metrics.full_answer(row)

    row.parts[0].cited_section_ids.append("returns")
    row.parts[2].text = "Delivery options"
    assert not metrics.full_answer(row)


def test_no_answer_uses_eval_item_answerability_for_scoring_and_denominator():
    row = _legacy("no_answer", [], accepted=True)
    row.item = row.item.model_copy(update={"group": "basic_policy"})
    assert metrics.noanswer_false_accept(row)
    assert metrics.part_metric_values(row) == {"noanswer_false_accept": True}


def test_graph_recall_and_mrr_read_each_part_top_five_when_the_question_was_split():
    # The merged list shows only the first part's chunks in its first five places.
    split = _legacy(
        "cross_doc",
        ["returns", "care"],
        retrieved=["returns", "a", "b", "c", "d"],
        parts=[
            {"text": "Policy returns?", "retrieved_section_ids": ["returns", "a", "b", "c", "d"]},
            {"text": "Product care?", "retrieved_section_ids": ["x", "care", "y"]},
        ],
    )
    assert metrics.graph_recall_at_5(split) == 1.0
    assert metrics.graph_mrr_at_5(split) == 1.0
    missing = split.model_copy(deep=True)
    missing.parts[1].retrieved_section_ids = ["x", "y", "z", "w", "v", "care"]
    assert metrics.graph_recall_at_5(missing) == 0.5


def test_graph_recall_and_mrr_are_unchanged_for_whole_questions():
    whole = _legacy(
        "cross_doc", ["returns", "care"], retrieved=["a", "returns", "b", "c", "d", "care"]
    )
    assert (
        metrics.graph_recall_at_5(whole)
        == metrics.recall_at_k(whole.retrieved_section_ids, ["returns", "care"], 5)
        == 0.5
    )
    assert (
        metrics.graph_mrr_at_5(whole)
        == metrics.mrr(whole.retrieved_section_ids, ["returns", "care"])
        == 0.5
    )
