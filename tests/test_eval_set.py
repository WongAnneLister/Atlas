from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
from eval.common import near_duplicate, set_hash, supported, term_present
from eval.drafter import Drafter
from eval.faq_candidates import candidate
from eval.schema import GROUPS, EvalItem, Section
from eval.split_set import sample_split
from eval.validate_set import validate_items
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from pydantic import ValidationError

from support_agent.config import get_settings
from support_agent.llm import override_chat_model


def item(**changes: object) -> EvalItem:
    values: dict[str, object] = dict(
        id="fixture",
        group="basic_policy",
        split="dev",
        question="What is the return window?",
        gold_sections=["returns.window"],
        answer_points=["Returns within 30 days."],
        answerable=True,
        source="fixture",
        reviewed=False,
    )
    values.update(changes)
    return EvalItem.model_validate(values)


@pytest.fixture
def sections() -> dict[str, Section]:
    return {
        "returns.window": Section(
            section_id="returns.window", doc_id="returns", text="Returns within 30 days."
        ),
        "returns.fee": Section(
            section_id="returns.fee", doc_id="returns", text="Return shipping is free."
        ),
        "payments.coupon": Section(
            section_id="payments.coupon", doc_id="payments", text="Coupons cannot be restored."
        ),
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"group": "no_answer"},
        {"gold_sections": []},
        {"answerable": False},
        {"group": "cross_doc"},
        {"answer_points": [""]},
        {"reviewed": "yes"},
    ],
)
def test_schema_rejects_inconsistent_records(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        item(**changes)


def test_no_answer_and_document_aware_cross_doc_schema() -> None:
    assert not item(
        group="no_answer", answerable=False, gold_sections=[], answer_points=[]
    ).answerable
    record = item(group="cross_doc", gold_sections=["returns.window", "payments.coupon"])
    EvalItem.model_validate(
        record.model_dump(),
        context={
            "section_docs": {"returns.window": "returns", "payments.coupon": "payments"},
        },
    )
    with pytest.raises(ValidationError, match="different documents"):
        EvalItem.model_validate(
            record.model_dump(),
            context={
                "section_docs": {"returns.window": "returns", "payments.coupon": "returns"},
            },
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"gold_sections": ["missing"]}, "missing sections"),
        ({"answer_points": ["Returns within 60 days."]}, "unsupported answer point"),
        ({"answer_points": ["Return 30%."]}, "unsupported answer point"),
        (
            {"group": "cross_doc", "gold_sections": ["returns.window", "returns.fee"]},
            "different documents",
        ),
        ({"gold_sections": ["returns.window", "payments.coupon"]}, "unused gold section"),
    ],
)
def test_validator_reports_label_errors(
    sections: dict[str, Section],
    changes: dict[str, object],
    message: str,
) -> None:
    failures = validate_items([item(**changes)], sections, get_settings().evaluation, counts=False)
    assert any(message in failure for failure in failures)


def test_validator_catches_cross_group_dev_test_leak(sections: dict[str, Section]) -> None:
    first = item()
    second = item(id="test", group="colloquial", split="test", question="what is the return window")
    assert any(
        "Dev/test near-duplicate" in error
        for error in validate_items(
            [first, second],
            sections,
            get_settings().evaluation,
            counts=False,
        )
    )
    assert validate_items([first], sections, get_settings().evaluation, counts=False) == []


def test_numeric_phrase_support_and_absence_boundaries() -> None:
    assert supported("30 days", "Return within 30 days.", 0.65)
    assert not supported("60 days", "Return within 30 days.", 0.65)
    assert term_present("Cash App Pay", "Methods: CASH APP PAY, cards.")
    assert not term_present("Pay", "PayPal only")
    assert near_duplicate(
        "Can I return a damaged item?", "can i return a damaged item", get_settings().evaluation
    )


def test_split_sampling_is_repeatable_balanced_and_keeps_families() -> None:
    config = get_settings().evaluation.model_copy(update={"per_group": 2, "dev_per_group": 1})
    subjects = [
        "orchids",
        "volcanoes",
        "pyramids",
        "whales",
        "mushrooms",
        "nebulae",
        "waterfalls",
        "diamonds",
        "mangroves",
        "satellites",
    ]
    pool = []
    for index, group in enumerate(GROUPS):
        for subject in subjects[index * 2 : index * 2 + 2]:
            # Strongly different terms avoid accidental similarity across fixture groups.
            gold = [] if group == "no_answer" else ["returns.window"]
            if group == "cross_doc":
                gold.append("payments.coupon")
            points = [] if group == "no_answer" else ["Returns within 30 days."]
            pool.append(candidate(group, subject, gold, points, "fixture", subject))
    first, audit = sample_split(pool, config)
    second, _ = sample_split(pool, config)
    assert first == second and audit["split_components"] == len(pool)
    assert Counter((row.group, row.split) for row in first) == Counter(
        {(group, split): 1 for group in GROUPS for split in ("dev", "test")}
    )
    assert set_hash(first) == set_hash([row.model_copy(update={"reviewed": True}) for row in first])
    assert set_hash(first) != set_hash(
        [first[0].model_copy(update={"question": "changed"}), *first[1:]]
    )


def test_sampler_refuses_impossible_nonleaking_split() -> None:
    config = get_settings().evaluation.model_copy(
        update={"per_group": 2, "dev_per_group": 1, "split_search_attempts": 2}
    )
    one = candidate("no_answer", "Unknown A", [], [], "fixture", "same")
    two = candidate("no_answer", "Unknown B", [], [], "fixture", "same")
    with pytest.raises(ValueError, match="without leakage"):
        sample_split([one, two], config)


def test_fake_drafter_is_cached_and_returns_only_question(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings().model_copy(deep=True)
    settings.evaluation.draft_mode = "fast"
    path = tmp_path / "cache.json"
    with override_chat_model(
        "fast", FakeListChatModel(responses=['{"question":"What are the terms?"}'])
    ):
        assert (
            Drafter(settings, path).question("Draft", {"gold": "fixed by code"})
            == "What are the terms?"
        )

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Cached draft called a model")

    monkeypatch.setattr("eval.drafter.get_chat_model", forbidden)
    assert (
        Drafter(settings, path).question("Draft", {"gold": "fixed by code"})
        == "What are the terms?"
    )
