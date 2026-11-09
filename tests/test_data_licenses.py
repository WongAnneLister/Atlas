"""Offline tests for the license classifier and report renderer."""

from __future__ import annotations

from typing import Any

import pytest

from support_agent.config import DataSource
from support_agent.data.licenses import Redistribute, build_report, classify, render


def _src(note: str | None = None) -> DataSource:
    return DataSource(
        name="d", repo_id="org/d", revision="abc", role="t", files=["f"], third_party_note=note
    )


@pytest.mark.parametrize(
    ("card", "expected"),
    [
        ({"license": "mit"}, Redistribute.YES),
        ({"license": "CC-BY-4.0"}, Redistribute.YES),
        ({"license": ["apache-2.0"]}, Redistribute.YES),
        ({"license": "cdla-sharing-1.0"}, Redistribute.YES),
        ({"license": "cc-by-nc-4.0"}, Redistribute.NO),
        ({"license": "cc-by-nc-sa-4.0"}, Redistribute.NO),
        ({"license": "cc-by-nd-4.0"}, Redistribute.NO),
        ({}, Redistribute.UNCLEAR),
        ({"license": ""}, Redistribute.UNCLEAR),
        ({"license": "other"}, Redistribute.UNCLEAR),
        ({"license": "creativeml-openrail-m"}, Redistribute.UNCLEAR),
        ({"license": ["mit", "cc-by-nc-4.0"]}, Redistribute.UNCLEAR),
    ],
)
def test_classify(card: dict[str, Any], expected: Redistribute) -> None:
    assert classify(_src(), card).redistribute is expected


def test_missing_license_means_scripts_only() -> None:
    verdict = classify(_src(), {})
    assert verdict.license_id is None
    assert verdict.action.startswith("Scripts only")


def test_third_party_note_downgrades_permissive_to_unclear() -> None:
    verdict = classify(_src("Text copied from a store website."), {"license": "apache-2.0"})
    assert verdict.redistribute is Redistribute.UNCLEAR
    assert "store website" in verdict.reason
    assert verdict.action.startswith("Scripts only")


def test_third_party_note_keeps_no() -> None:
    verdict = classify(_src("copied"), {"license": "cc-by-nc-4.0"})
    assert verdict.redistribute is Redistribute.NO


def test_render_lists_every_dataset() -> None:
    verdicts = build_report([_src()], fetch=lambda repo_id, revision: {"license": "mit"})
    text = render(verdicts, "2026-01-01")
    assert "| [org/d](https://huggingface.co/datasets/org/d/tree/abc) | `mit` | **yes** |" in text
    assert "2026-01-01" in text
