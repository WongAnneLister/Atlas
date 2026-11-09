"""Shared local artifact IO, normalisation, and evidence support checks."""

from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from eval.schema import EvalItem, Section
from support_agent.config import REPO_ROOT, EvalSettings, Settings
from support_agent.data.doc_models import digest, numeric_tokens, write_text
from support_agent.data.validate_docs import parse_document


def normalised(text: str) -> str:
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold()))


def tokens(text: str) -> set[str]:
    return set(normalised(text).split())


def near_duplicate(left: str, right: str, config: EvalSettings) -> bool:
    a, b = normalised(left), normalised(right)
    ta, tb = set(a.split()), set(b.split())
    overlap = len(ta & tb) / len(ta | tb) if ta | tb else 1.0
    if overlap >= config.token_duplicate_threshold:
        return True
    if 2 * min(len(a), len(b)) / max(1, len(a) + len(b)) < config.near_duplicate_threshold:
        return False
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    return (
        matcher.quick_ratio() >= config.near_duplicate_threshold
        and matcher.ratio() >= config.near_duplicate_threshold
    )


def supported(point: str, text: str, threshold: float) -> bool:
    terms = tokens(point)
    if not terms or numeric_tokens(point) - numeric_tokens(text):
        return False
    return len(terms & tokens(text)) / len(terms) >= threshold


def term_present(term: str, corpus: str) -> bool:
    return f" {normalised(term)} " in f" {normalised(corpus)} "


def load_sections(settings: Settings) -> dict[str, Section]:
    folder = REPO_ROOT / settings.data.processed_dir / "docs"
    sections: dict[str, Section] = {}
    for path in sorted(folder.glob("*.md")):
        parsed, header = parse_document(path.read_text(encoding="utf-8"))
        for sid, text in parsed.items():
            if sid in sections:
                raise ValueError(f"Duplicate corpus section: {sid}")
            sections[sid] = Section(section_id=sid, doc_id=header.doc_id, text=text)
    if not sections:
        raise ValueError("No policy documents; run make data-docs")
    return sections


def load_items(path: Path) -> list[EvalItem]:
    return [
        EvalItem.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def save_items(path: Path, items: list[EvalItem]) -> None:
    write_text(path, "".join(item.model_dump_json() + "\n" for item in items))


def set_hash(items: list[EvalItem]) -> str:
    """Review status is mutable; frozen questions and gold labels are not."""
    return digest(json.dumps([i.model_dump(exclude={"reviewed"}) for i in items], sort_keys=True))
