from __future__ import annotations

import csv
from pathlib import Path

import pytest
from eval.review import FIELDS, export_review, import_review
from eval.schema import EvalItem, Section


def fixtures() -> tuple[list[EvalItem], dict[str, Section]]:
    items = [
        EvalItem(
            id=identity,
            group="no_answer",
            split="dev",
            question=question,
            gold_sections=[],
            answer_points=[],
            answerable=False,
            source="fixture",
            reviewed=False,
        )
        for identity, question in [("a", "Unknown volcano terms?"), ("b", "Unknown orchard terms?")]
    ]
    return items, {"s": Section(section_id="s", doc_id="returns", text="Returns within 30 days.")}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_review_only_marks_human_ok_and_preserves_labels(tmp_path: Path) -> None:
    items, sections = fixtures()
    path = tmp_path / "review.csv"
    export_review(items, sections, path)
    rows = read_csv(path)
    assert [row["ok"] for row in rows] == ["", ""]
    rows[0]["ok"], rows[1]["ok"] = "ok", "yes"
    write_csv(path, rows)
    updated = import_review(items, sections, path)
    assert [row.reviewed for row in updated] == [True, False]
    assert [row.model_dump(exclude={"reviewed"}) for row in updated] == [
        row.model_dump(exclude={"reviewed"}) for row in items
    ]
    assert all(not row.reviewed for row in items)
    with pytest.raises(ValueError, match="decisions"):
        export_review(updated, sections, path)


@pytest.mark.parametrize("mutation", ["question", "answer_points", "id", "duplicate", "corpus"])
def test_review_rejects_edited_or_stale_content(tmp_path: Path, mutation: str) -> None:
    items, sections = fixtures()
    path = tmp_path / "review.csv"
    export_review(items, sections, path)
    rows = read_csv(path)
    rows[0]["ok"] = "ok"
    if mutation == "duplicate":
        rows.append(rows[0])
    elif mutation == "corpus":
        sections["s"] = sections["s"].model_copy(
            update={"text": "Changed even without any gold sections"}
        )
    else:
        rows[1][mutation] = "tampered"
    write_csv(path, rows)
    with pytest.raises(ValueError):
        import_review(items, sections, path)
    assert all(not row.reviewed for row in items)
