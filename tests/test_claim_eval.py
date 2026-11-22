import csv
import io
from collections import Counter
from random import Random

import pytest
from eval.build_claims import build_claim_set, synthetic_build_lines
from eval.claim_labels import (
    export_labels,
    export_review,
    import_drafts,
    import_labels,
    import_review,
)
from eval.claim_perturbations import Perturbations
from eval.claims import extract_claims
from eval.claims_eval import score_claims
from eval.e2e_records import E2EMetadata, E2ERecord
from eval.e2e_runs import prepare_e2e
from eval.metrics import claim_answer_metrics, claim_support_observations
from eval.schema import EvalItem, Section

from support_agent.grounding.split import answer_sentences


def record(split="test", **changes):
    return E2ERecord(
        item=EvalItem(
            id="item-" + split,
            group="basic_policy",
            split=split,
            question="What are the terms?",
            gold_sections=["returns"],
            answer_points=["Returns take 30 days."],
            answerable=True,
            source="fixture",
        ),
        latency_full_answer_s=0,
        **{
            "path": "B",
            "accepted": True,
            "answer": "Returns take 30 days. The fee is $4.50. A BHD340/10 is covered. [2]",
            "citations": [{"n": 2, "section_id": "returns"}],
            "cited_sources": [
                {
                    "section_id": "returns",
                    "text": "Returns take 30 days. The fee is $4.50. A BHD340/10 is covered.",
                }
            ],
            **changes,
        },
    )


def test_splitter_handles_abbreviations_lists_decimals_and_model_ids():
    assert answer_sentences(
        "1. The Philips BHD340/10 weighs 1.25 kg, e.g. without its cable. [2]\n"
        "- It costs only $4.50. It is covered in the U.S. under this plan. [3]"
    ) == [
        "The Philips BHD340/10 weighs 1.25 kg, e.g. without its cable. [2]",
        "It costs only $4.50.",
        "It is covered in the U.S. under this plan. [3]",
    ]


def test_extraction_uses_only_released_paragraphs_and_their_citations():
    row = record(
        accepted=False,
        handoff_reason="unsupported_part",
        answer_status="partial",
        parts=[
            {"text": "Unsupported?", "handed_off": True},
            {"text": "When?", "answered": True, "cited_section_ids": ["returns"]},
            {"text": "What model?", "answered": True, "cited_section_ids": ["product"]},
        ],
        answer=(
            "Returns take 30 days. The fee is $4.50. [2]\n\n"
            "Try the BHD340/10. [4]\n\n"
            "I\u2019m passing the following to a human support agent: “Unsupported?”."
        ),
        citations=[
            {"n": 2, "section_id": "returns"},
            {"n": 4, "section_id": "product"},
            {"n": 5, "section_id": "uncited"},
        ],
        cited_sources=[
            {"section_id": "returns", "text": "Returns take 30 days. The fee is $4.50."},
            {"section_id": "product", "text": "Try the BHD340/10."},
            {"section_id": "uncited", "text": "Unused."},
        ],
    )
    claims = extract_claims(row, "run")
    assert [(c.part, c.sentence, c.claim) for c in claims] == [
        (1, 0, "Returns take 30 days."),
        (1, 1, "The fee is $4.50."),
        (2, 0, "Try the BHD340/10."),
    ]
    assert [claim.question for claim in claims] == ["When?", "When?", "What model?"]
    assert [[source.n for source in c.sources] for c in claims] == [[2], [2], [4]]
    assert extract_claims(row.model_copy(update={"answer_status": None}), "run") == []
    assert extract_claims(row.model_copy(update={"path": "C"}), "run") == []


def test_extraction_ignores_historical_template_and_reads_legacy_rows():
    row = record(
        answer=(
            "Returns take 30 days. [2]\n\nYour order was placed on 2026-06-01. "
            "The policy that applied then was in effect from 2026-01-01 until 2026-09-01 [2]."
        )
    )
    legacy = E2ERecord.model_validate(row.model_dump(exclude={"claims"}))
    assert legacy.claims is None
    [claim] = extract_claims(legacy, "run")
    assert claim.claim == "Returns take 30 days."
    assert claim.question == legacy.item.question


def make_claim_set():
    rows = [*extract_claims(record(), "test-run"), *extract_claims(record("dev"), "dev-run")]
    sections = {
        "returns": Section(section_id="returns", doc_id="same-doc", text=rows[0].sources[0].text),
        "foreign": Section(
            section_id="foreign",
            doc_id="other-doc",
            text="Product pickup closes at noon every Saturday.",
        ),
    }
    options = dict(
        seed=8,
        real_targets={"dev": 2, "test": 2},
        synthetic_per_split=3,
        cap=2,
        support_overlap=0.65,
    )
    return rows, sections, options


def test_builder_balances_splits_caps_items_and_keeps_perturbations_blind():
    rows, sections, options = make_claim_set()
    built = build_claim_set(rows, sections, **options)
    assert built == build_claim_set(list(reversed(rows)), sections, **options)
    assert Counter((row.split, row.group) for row in built) == {
        ("dev", "real"): 2,
        ("test", "real"): 2,
        ("dev", "synthetic"): 3,
        ("test", "synthetic"): 3,
    }
    for item in built:
        source = next(
            c
            for c in rows
            if (c.split, c.source_item, c.part, c.sentence)
            == (item.split, item.source_item, item.part, item.sentence)
        )
        assert item.sources == source.sources
        assert item.label is None and not item.reviewed
        assert (item.claim != source.claim) == (item.group == "synthetic")


def test_csv_carries_only_human_inputs_and_refuses_invalid_labels(tmp_path):
    rows, sections, options = make_claim_set()
    items = build_claim_set(rows, sections, **options)
    path = tmp_path / "review.csv"
    export_labels(items, path)
    with path.open(newline="", encoding="utf-8") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert len(csv_rows) == 4
    assert all(row["label"] == row["note"] == "" for row in csv_rows)
    assert {row["question"] for row in csv_rows} == {"What are the terms?"}
    assert not {"group", "verdict", "prediction"} & csv_rows[0].keys()

    def write(rows):
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(csv_rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        path.write_text(buffer.getvalue(), encoding="utf-8")

    with pytest.raises(ValueError, match="label"):
        import_labels(items, path)
    for row in csv_rows:
        row["label"] = "supported"
    for field, value, match in (
        ("id", "unknown", "Unknown"),
        ("claim", "edited", "changed"),
        ("question", "edited", "changed"),
    ):
        write([{**csv_rows[0], field: value}, *csv_rows[1:]])
        with pytest.raises(ValueError, match=match):
            import_labels(items, path)
    write(csv_rows)
    imported = import_labels(items, path)
    assert sum(item.reviewed for item in imported) == 4
    assert all(item.label is None for item in imported if item.group == "synthetic")


def test_metrics_use_micro_claim_rate_and_keep_groups_separate():
    row = record(
        claims=[
            {"part": 0, "text": "A", "verdict": "supported", "reason": "quote", "removed": False},
            {"part": 0, "text": "B", "verdict": "partial", "reason": "missing", "removed": True},
        ],
    )
    handoff = record(
        accepted=False,
        claims=[
            {"part": 0, "text": "C", "verdict": "unsupported", "reason": "absent", "removed": True},
        ],
        handoff_reason="low_grounding",
    )
    assert claim_support_observations([row, handoff, record()]) == [True, False, False]
    assert claim_answer_metrics(row) == {
        "answers_with_any_unsupported_claim": True,
        "claims_removed_per_answer": 1.0,
        "low_grounding_handoff_rate": False,
    }
    assert claim_answer_metrics(handoff)["low_grounding_handoff_rate"] is True
    assert claim_answer_metrics(record()) == {}
    rows, sections, options = make_claim_set()
    items = build_claim_set(rows, sections, **options)
    outcomes = {item.id: "unsupported" for item in items}
    groups = score_claims(items, outcomes, alpha=0.05)
    assert groups["test", "real"].labelled == 0
    assert groups["test", "synthetic"].recall.point == 1
    assert groups["dev", "synthetic"].f1.low < 1


def test_perturbations_keep_units_and_do_not_introduce_cited_values():
    text = "The BHD340/10 costs $4.50, takes 30 business days, and includes 2 attachments."
    row = record(answer=text + " [2]", cited_sources=[{"section_id": "returns", "text": text}])
    [item] = extract_claims(row, "run")
    sections = {
        "returns": Section(section_id="returns", doc_id="returns", text=text),
        "other": Section(
            section_id="other",
            doc_id="other",
            text=(
                "Click here to check when the service starts. "
                "Our options for new customers and shops. "
                "See https://example.com for the complete product options. "
                "Pickup closes at noon. HD999/21 has a safety switch for overheating."
            ),
        ),
    }
    variants = dict(Perturbations(sections, 0.65).variants(item, Random(1)))
    assert variants.keys() == {"amount", "duration", "number", "model", "uncited_sentence"}
    assert "$5.50" in variants["amount"]
    assert "31 business days" in variants["duration"]
    assert "3 attachments" in variants["number"]
    assert "HD999/21" in variants["model"]
    assert variants["uncited_sentence"] == "HD999/21 has a safety switch for overheating."


def test_run_metrics_summarize_claims_and_preserve_acceptance():
    metadata = E2EMetadata(
        git_sha="fixture",
        config_hash="config",
        eval_file_hash="eval",
        corpus_hash="corpus",
        models={},
        dataset_versions={},
        split="test",
        date="2026-11-22T00:00:00Z",
        customer_id="fixture",
        threshold=0.15,
    )
    supported = dict(part=0, text="A", verdict="supported", reason="quote", removed=False)
    unsupported = dict(part=0, text="B", verdict="unsupported", reason="absent", removed=True)
    short = record(claims=[supported])
    long = record(claims=[supported, unsupported, unsupported])
    handoff = record(accepted=False, claims=[], handoff_reason="low_grounding")
    run = prepare_e2e(metadata, [short, long, handoff])
    report = run.metrics.metrics
    assert report["claim_support_rate"].count == 2
    assert report["claim_support_rate"].n == 4
    assert report["claim_support_rate"].interval.point == 0.5
    assert report["claims_removed_per_answer"].interval.point == 1
    assert report["answers_with_any_unsupported_claim"].count == 1
    assert report["low_grounding_handoff_rate"].count == 1
    assert [row.metrics["pass_rate"] for row in run.items] == [True, True, False]


def test_splitter_keeps_currency_and_units_with_their_values():
    assert answer_sentences(
        "It costs Rs. 349. The previous price was Rs 499. "
        "The package weighs approx. 2 kg. with the cable. Check item no. 8 for details."
    ) == [
        "It costs Rs. 349.",
        "The previous price was Rs 499.",
        "The package weighs approx. 2 kg. with the cable.",
        "Check item no. 8 for details.",
    ]


def test_splitter_merges_fragments_within_each_paragraph():
    assert answer_sentences(
        "Yes.\nThe dryer draws up to 1,600 watts. 1600 W.\n\n"
        "No.\nThe charger does not come with it.\n\nOkay."
    ) == [
        "Yes. The dryer draws up to 1,600 watts. 1600 W.",
        "No. The charger does not come with it.",
        "Okay.",
    ]


def test_extraction_drops_configured_generic_phrases_before_merging(monkeypatch):
    from support_agent.config import get_settings

    monkeypatch.setattr(get_settings().grounding, "generic_phrases", ["Thanks."])
    [claim] = extract_claims(record(answer="THANKS! Returns take 30 days. [2]"), "run")
    assert claim.claim == "Returns take 30 days."


def test_builder_caps_uncited_and_reports_soft_perturbation_shortfalls():
    rows, sections, options = make_claim_set()
    items = build_claim_set(rows, sections, **options)
    for split in ("dev", "test"):
        negatives = [row for row in items if row.split == split and row.group == "synthetic"]
        assert sum(row.perturbation == "uncited_sentence" for row in negatives) <= 1
    lines = synthetic_build_lines(items, min_duration=5, min_amount=5)
    assert any("uncited_sentence=1" in line for line in lines)
    assert any("dev" in line and "duration" in line and "shortfall" in line for line in lines)
    assert any("test" in line and "amount" in line and "shortfall" in line for line in lines)
    scores = score_claims(items, {item.id: "unsupported" for item in items}, alpha=0.05)
    assert scores["test", "synthetic / uncited_sentence"].total == 1
    assert scores["test", "synthetic / number"].total == 0


def test_tooling_draft_without_question_requires_rebuild(tmp_path):
    from eval.build_claims import read_claims

    [item, *_] = extract_claims(record(), "run")
    path = tmp_path / "claims.jsonl"
    path.write_text(item.model_dump_json(exclude={"question"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="tooling draft"):
        read_claims(path)


def test_synthetic_sampling_meets_available_duration_and_amount_minima():
    answer = "Returns take 30 days and cost Rs. 349."
    [claim] = extract_claims(
        record(answer=f"{answer} [2]", cited_sources=[{"section_id": "returns", "text": answer}]),
        "run",
    )
    claims = [
        claim.model_copy(update={"id": f"c{index}", "source_item": f"item{index}"})
        for index in range(5)
    ]
    items = build_claim_set(
        claims,
        {},
        seed=8,
        real_targets={"test": 1},
        synthetic_per_split=10,
        cap=1,
        support_overlap=0.65,
        splits=["test"],
    )
    assert Counter(item.perturbation for item in items if item.group == "synthetic") == {
        "duration": 5,
        "amount": 5,
    }
    assert len(synthetic_build_lines(items, min_duration=5, min_amount=5)) == 1


def test_splitter_breaks_inline_numbered_lists_without_gluing_item_numbers():
    from support_agent.grounding.split import sentence_candidates

    steps = "To change it: 1. Go to My Account. 2. Choose Update Email. 3. Enter the code."
    assert sentence_candidates(steps) == [
        "To change it:",
        "Go to My Account.",
        "Choose Update Email.",
        "Enter the code.",
    ]
    inline = "You can return it 1. Go to My Orders 2. Choose the item 3. Submit the request."
    assert all(
        not sentence.rstrip(".").endswith((" 2", " 3")) for sentence in sentence_candidates(inline)
    )
    # A lone number before a capital letter is not a list.
    assert sentence_candidates("The fee is 40. You can pay online.") == [
        "The fee is 40.",
        "You can pay online.",
    ]


def test_model_drafts_stay_marked_until_the_author_reviews_a_blind_sample(tmp_path):
    rows, sections, options = make_claim_set()
    items = build_claim_set(rows, sections, **options)
    path = tmp_path / "labels.csv"
    export_labels(items, path)
    with path.open(newline="", encoding="utf-8") as handle:
        csv_rows = list(csv.DictReader(handle))
    for index, row in enumerate(csv_rows):
        row["label"] = "unsupported" if index == 0 else "supported"
        row["note"] = "model reason"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(csv_rows[0]))
        writer.writeheader()
        writer.writerows(csv_rows)
    drafted = import_drafts(items, path)
    real = [item for item in drafted if item.group == "real"]
    assert all(item.label_source == "model_draft" and not item.reviewed for item in real)
    assert all(item.draft_label == item.label and item.note == "" for item in real)

    review = tmp_path / "review.csv"
    export_review(drafted, review, size=1, seed=7)
    with review.open(newline="", encoding="utf-8") as handle:
        sample = list(csv.DictReader(handle))
    # Every drafted unsupported claim is reviewed, plus the seeded sample; the sheet is blind.
    assert csv_rows[0]["id"] in {row["id"] for row in sample} and len(sample) == 2
    assert all(row["label"] == row["note"] == "" for row in sample)
    for row in sample:
        row["label"] = "supported"
    with review.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(sample[0]))
        writer.writeheader()
        writer.writerows(sample)
    final, agreement = import_review(drafted, review)
    assert agreement["reviewed"] == 2 and agreement["agree"] == 1
    assert agreement["changed"] == [csv_rows[0]["id"]]
    by_id = {item.id: item for item in final}
    changed = by_id[csv_rows[0]["id"]]
    assert changed.label == "supported" and changed.draft_label == "unsupported"
    assert changed.label_source == "human" and changed.reviewed
    untouched = [item for item in final if item.label_source == "model_draft"]
    assert len(untouched) == 2 and not any(item.reviewed for item in untouched)
