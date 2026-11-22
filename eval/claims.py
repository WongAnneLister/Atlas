"""Extract claims and their saved evidence without calling a model or a retriever."""

from __future__ import annotations

import re
from functools import cache
from string import Formatter

from eval.e2e_records import E2ERecord
from eval.schema import ClaimItem, ClaimSource
from support_agent.data.doc_models import digest
from support_agent.graph.handoff import PROMPTS
from support_agent.graph.intents import Path
from support_agent.grounding.split import CITATION, answer_sentences

_PARAGRAPH = re.compile(r"\n\s*\n")
_CITED_END = re.compile(r"\[\d+\](?:\s*\[\d+\])*\s*[.!?]?$")


@cache
def _templates() -> tuple[re.Pattern[str], ...]:
    names = ("policy_version_notice.txt", "partial_handoff.txt")
    return tuple(
        re.compile(
            "".join(
                re.escape(literal) + (r".+?" if field is not None else "")
                for literal, field, _, _ in Formatter().parse(
                    (PROMPTS / name).read_text(encoding="utf-8").strip()
                )
            ),
            re.DOTALL,
        )
        for name in names
    )


def _numbered_sources(record: E2ERecord) -> dict[int, ClaimSource]:
    sources = {}
    # The collector stores the text in citation order, without a copy of the number.
    if len(record.citations) != len(record.cited_sources):
        raise ValueError(f"Mismatched citation snapshot for {record.item.id}")
    for citation, saved in zip(record.citations, record.cited_sources, strict=True):
        number = citation.get("n")
        if (
            type(number) is not int
            or number in sources
            or citation.get("section_id") != saved.get("section_id")
            or (
                "heading_path" in citation and citation["heading_path"] != saved.get("heading_path")
            )
        ):
            raise ValueError(f"Invalid citation snapshot for {record.item.id}")
        sources[number] = ClaimSource(n=number, section_id=saved["section_id"], text=saved["text"])
    return sources


def _released_paragraphs(record: E2ERecord) -> list[str]:
    paragraphs = [
        block
        for block in _PARAGRAPH.split(record.answer.strip())
        if block and not any(pattern.fullmatch(block) for pattern in _templates())
    ]
    expected = sum(part.answered for part in record.parts) if record.parts is not None else 1
    if len(paragraphs) <= expected:
        return paragraphs
    # The renderer appends citations to the end of each part. A model answer can
    # itself contain blank lines before that suffix.
    combined: list[str] = []
    pending: list[str] = []
    for paragraph in paragraphs:
        pending.append(paragraph)
        if _CITED_END.search(paragraph):
            combined.append("\n\n".join(pending))
            pending.clear()
    if pending:
        combined.append("\n\n".join(pending))
    return combined


def extract_claims(record: E2ERecord, source_run: str) -> list[ClaimItem]:
    """Extract only released knowledge text, in observed part and sentence order."""
    if record.path not in {Path.KNOWLEDGE, "knowledge"} and not (
        record.path is None and "answer" in record.trace
    ):
        return []
    is_partial = record.answer_status == "partial" and any(
        part.answered for part in record.parts or []
    )
    if not record.accepted and not is_partial:
        return []

    paragraphs = _released_paragraphs(record)
    indices = (
        [index for index, part in enumerate(record.parts) if part.answered]
        if record.parts is not None
        else [0] * len(paragraphs)
    )
    if len(indices) != len(paragraphs):
        raise ValueError(f"Cannot identify the released parts for {record.item.id}")

    numbered = _numbered_sources(record)
    claims: list[ClaimItem] = []
    offsets: dict[int, int] = {}
    for part, text in zip(indices, paragraphs, strict=True):
        numbers = list(dict.fromkeys(int(n) for n in CITATION.findall(text)))
        if any(n not in numbered for n in numbers):
            raise ValueError(f"Missing cited text for {record.item.id}, part {part}")
        sources = [numbered[n] for n in numbers]
        if record.parts is not None and (
            {source.section_id for source in sources} != set(record.parts[part].cited_section_ids)
        ):
            raise ValueError(f"Cannot match cited text to {record.item.id}, part {part}")
        clean = re.sub(r"\s+([,.!?;:])", r"\1", CITATION.sub("", text))
        for sentence, claim in enumerate(answer_sentences(clean), start=offsets.get(part, 0)):
            offsets[part] = sentence + 1
            identifier = digest(f"{source_run}\n{record.item.id}\n{part}\n{sentence}")
            claims.append(
                ClaimItem(
                    id=f"claim-{record.item.split}-{identifier}",
                    split=record.item.split,
                    group="real",
                    source_run=source_run,
                    source_item=record.item.id,
                    part=part,
                    sentence=sentence,
                    claim=claim,
                    sources=sources,
                    label_source="human",
                )
            )
    return claims
