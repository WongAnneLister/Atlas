"""Build and freeze the near-miss no-answer holdout from its authored draft file."""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from eval.common import load_items, load_sections, near_duplicate, save_items, set_hash
from eval.schema import EvalItem, Section
from support_agent.config import REPO_ROOT, EvalSettings, get_settings
from support_agent.data.doc_models import digest, write_text

log = logging.getLogger(__name__)


class HoldoutSpec(BaseModel):
    draft: Path
    output: Path
    report: Path
    source_prefix: str


# Each version is frozen in its own commit before the change it judges.
VERSIONS = {
    "v1": HoldoutSpec(
        draft=Path("eval/drafts/near_miss_holdout.yaml"),
        output=Path("eval/sets/holdout_near_miss_v1.jsonl"),
        report=Path("eval/reports/holdout_near_miss.md"),
        source_prefix="holdout:near_miss_v1",
    ),
    "v2": HoldoutSpec(
        draft=Path("eval/drafts/near_miss_holdout_v2.yaml"),
        output=Path("eval/sets/holdout_near_miss_v2.jsonl"),
        report=Path("eval/reports/holdout_near_miss_v2.md"),
        source_prefix="holdout:near_miss_v2",
    ),
}
OUTPUT = VERSIONS["v1"].output


class DraftItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    q: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    absent: list[str] = Field(min_length=1)
    closed_list: bool = False


class DraftFamily(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str
    closed_list: bool = False
    items: list[DraftItem] = Field(min_length=1)


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    families: dict[str, DraftFamily]


def scope_sections(scope: str, sections: dict[str, Section]) -> list[str]:
    """Return the section ids a draft scope covers; unknown scopes are errors."""
    kind, _, model = scope.partition(":")
    if kind == "corpus" and not model:
        ids = list(sections)
    elif kind == "flipkart" and not model:
        ids = [sid for sid in sections if ".flipkart_faqs." in sid]
    elif kind == "generic" and not model:
        ids = [sid for sid in sections if ".maktek_faqs." in sid]
    elif kind == "product" and model:
        ids = [f"product.{model}"] if f"product.{model}" in sections else []
    else:
        raise ValueError(f"Unknown holdout scope: {scope}")
    if not ids:
        raise ValueError(f"Holdout scope has no sections: {scope}")
    return ids


def phrase_present(phrase: str, text: str) -> bool:
    """Case-insensitive whole-phrase match; avoids substring hits such as 'rs.' in 'others.'."""
    pattern = r"(?<!\w)" + re.escape(phrase.strip().casefold()) + r"(?!\w)"
    return re.search(pattern, text.casefold()) is not None


def item_id(question: str) -> str:
    return "near_miss-" + digest(question)


def build_items(
    draft: Draft,
    sections: dict[str, Section],
    existing: list[EvalItem],
    config: EvalSettings,
    source_prefix: str = VERSIONS["v1"].source_prefix,
) -> list[EvalItem]:
    """Validate every draft question and return frozen no-answer records."""
    errors: list[str] = []
    items: list[EvalItem] = []
    for family_name, family in draft.families.items():
        for draft_item in family.items:
            ids = scope_sections(draft_item.scope, sections)
            text = " ".join(sections[sid].text for sid in ids)
            present = [phrase for phrase in draft_item.absent if phrase_present(phrase, text)]
            if present:
                errors.append(f"{draft_item.q!r}: phrase present in {draft_item.scope}: {present}")
            for other in [*existing, *items]:
                if near_duplicate(draft_item.q, other.question, config):
                    errors.append(f"{draft_item.q!r}: near duplicate of {other.id}")
            closed = family.closed_list or draft_item.closed_list
            items.append(
                EvalItem(
                    id=item_id(draft_item.q),
                    group="no_answer",
                    split="test",
                    question=draft_item.q,
                    gold_sections=[],
                    answer_points=[],
                    answerable=False,
                    source=f"{source_prefix}:{family_name}",
                    notes=json.dumps(
                        {
                            "family": family_name,
                            "scope": draft_item.scope,
                            "absent": draft_item.absent,
                            "closed_list": closed,
                        },
                        sort_keys=True,
                    ),
                )
            )
    if len({item.id for item in items}) != len(items):
        errors.append("Duplicate holdout questions")
    if errors:
        raise ValueError("Holdout validation failed:\n" + "\n".join(errors))
    return items


def family_of(item: EvalItem) -> str:
    return str(json.loads(item.notes)["family"])


def is_closed_list(item: EvalItem) -> bool:
    return bool(json.loads(item.notes)["closed_list"])


def write_report(items: list[EvalItem], draft_hash: str, spec: HoldoutSpec) -> None:
    path = REPO_ROOT / spec.report
    families: dict[str, list[EvalItem]] = {}
    for item in items:
        families.setdefault(family_of(item), []).append(item)
    lines = [
        "# Near-miss no-answer holdout",
        "",
        "Generated by `make eval-holdout-build`. Built and frozen before the change it judges.",
        "",
        f"- Draft file: `{spec.draft.as_posix()}`",
        f"- Draft hash: `{draft_hash}`",
        f"- Frozen set hash: `{set_hash(items)}`",
        f"- Items: {len(items)} (all `no_answer`, all unreviewed)",
        f"- Closed-list items: {sum(is_closed_list(item) for item in items)}",
        "- Validation: every absent phrase is missing from its scope; no near duplicates",
        "  of each other, of `eval_v1` questions, or of earlier holdout versions.",
        "",
        "| Family | Items | Closed-list |",
        "|---|---:|---:|",
    ]
    lines.extend(
        f"| {name} | {len(group)} | {sum(is_closed_list(item) for item in group)} |"
        for name, group in families.items()
    )
    lines.extend(
        [
            "",
            "## Limits",
            "",
            "The questions are agent-authored and unreviewed.",
            "Lexical absence in a scope is not proof that no source implies an answer.",
            "Closed-list items name a method missing from a positive list of accepted methods.",
            "A reviewer may judge such a list as a sufficient no; they are reported separately.",
            "This set measures false accepts only; it has no answerable items.",
        ]
    )
    write_text(path, "\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate without writing files")
    parser.add_argument("--version", choices=sorted(VERSIONS), default="v1")
    args = parser.parse_args(argv)
    spec = VERSIONS[args.version]
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = get_settings()
    try:
        raw = (REPO_ROOT / spec.draft).read_text(encoding="utf-8")
        draft = Draft.model_validate(yaml.safe_load(raw))
        existing = load_items(REPO_ROOT / settings.evaluation.sets_dir / "eval_v1.jsonl")
        for name, earlier in VERSIONS.items():
            if name < args.version:
                existing += load_items(REPO_ROOT / earlier.output)
        items = build_items(
            draft, load_sections(settings), existing, settings.evaluation, spec.source_prefix
        )
    except (OSError, ValueError) as error:
        log.error("holdout build failed: %s", error)
        return 1
    if not args.check:
        output = REPO_ROOT / spec.output
        if output.exists() and set_hash(load_items(output)) != set_hash(items):
            log.error("%s exists with different content; the holdout is frozen", spec.output)
            return 1
        output.parent.mkdir(parents=True, exist_ok=True)
        save_items(output, items)
        write_report(items, digest(raw), spec)
    log.info("holdout items: %d", len(items))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
