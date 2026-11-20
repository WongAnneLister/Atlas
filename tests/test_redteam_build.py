import json
import subprocess
from collections import Counter

import pytest
from eval.redteam_build import DEFAULT_OUTPUT, build_items, load_items, write_items
from eval.redteam_canaries import CANARY_IDS, build_canaries
from eval.redteam_models import CATEGORIES, RedTeamItem
from eval.registry import file_hash, load_registry
from pydantic import ValidationError

from support_agent.config import REPO_ROOT


def test_builder_output_is_deterministic_and_matches_registered_bytes(tmp_path) -> None:
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    write_items(first)
    write_items(second)
    entry = load_registry()["redteam_v1"]
    assert first.read_bytes() == second.read_bytes()
    assert file_hash(first) == entry.sha256
    assert REPO_ROOT / entry.path == DEFAULT_OUTPUT
    assert load_items(first) == build_items()
    assert {row["split"] for row in map(json.loads, first.read_text().splitlines())} == {
        "dev",
        "test",
    }


def test_frozen_set_covers_categories_splits_and_multi_turns() -> None:
    items = build_items()
    counts = Counter(item.category for item in items)
    assert set(counts) == set(CATEGORIES)
    assert len(items) >= 120
    assert min(counts.values()) >= 15
    assert {item.category for item in items if len(item.turns) > 1} >= {
        "prompt_injection_direct",
        "cross_customer_access",
        "refund_fraud",
    }
    assert len({item.id for item in items}) == len(items)
    assert all(item.id.startswith(f"{item.category}-") for item in items)
    assert all(
        {item.split for item in items if item.category == category} == {"dev", "test"}
        for category in CATEGORIES
    )
    assert all(len(item.turns) == 1 or 3 <= len(item.turns) <= 5 for item in items)


def test_invalid_turn_count_is_rejected() -> None:
    row = build_items()[0].model_dump()
    row["turns"] = [row["turns"][0]] * 2
    with pytest.raises(ValidationError, match="one turn or between three and five"):
        RedTeamItem.model_validate(row)


def test_canaries_are_unique_seeded_and_absent_from_tracked_files() -> None:
    canaries = build_canaries()
    assert tuple(canaries) == CANARY_IDS
    assert canaries == build_canaries()
    assert len(set(canaries.values())) == len(canaries)
    assert all(value.startswith("ATLAS-CANARY-") for value in canaries.values())
    assert set(canaries.values()).isdisjoint(build_canaries(seed=21).values())
    # git grep checks both tracked prompt/source files and tracked production assets.
    result = subprocess.run(
        [
            "git",
            "grep",
            "-F",
            "-l",
            *[part for token in canaries.values() for part in ("-e", token)],
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout.decode(errors="replace")


@pytest.mark.parametrize("name", ["orders.sqlite", "settings.yaml"])
def test_builder_rejects_other_file_types(tmp_path, name) -> None:
    output = tmp_path / name
    output.write_text("keep me")
    with pytest.raises(ValueError, match="JSONL"):
        write_items(output)
    assert output.read_text() == "keep me"


@pytest.mark.parametrize("link", ["symlink_to", "hardlink_to"])
def test_builder_does_not_modify_linked_files(tmp_path, link) -> None:
    protected = tmp_path / "protected.sqlite"
    protected.write_text("keep me")
    output = tmp_path / "redteam.jsonl"
    getattr(output, link)(protected)
    with pytest.raises(ValueError, match="ordinary regular file"):
        write_items(output)
    assert protected.read_text() == "keep me"
    assert output.read_text() == "keep me"


def test_refund_cases_never_claim_a_defect() -> None:
    # A damaged item can make a final-sale or late order legitimately refundable.
    refunds = [item for item in build_items() if item.category == "refund_fraud"]
    assert {item.success.scenario for item in refunds if item.success.kind == "refund_created"} == {
        "already_refunded",
        "final_sale",
        "expired",
        "repeated",
    }
    words = ("broken", "damaged", "defect", "faulty", "stopped working")
    assert not any(
        word in turn.text.lower() for item in refunds for turn in item.turns for word in words
    )
