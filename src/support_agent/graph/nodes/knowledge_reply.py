"""Render and publish a knowledge reply after its evidence checks."""

import re
from typing import Any

from langchain_core.messages import AIMessage

from support_agent.graph.handoff import PROMPTS, HandoffReason, make_handoff, mark_parts_handed_off
from support_agent.graph.state import CitationRecord, ConversationState
from support_agent.grounding.split import CITATION
from support_agent.retrieval.types import RetrievedChunk

_PARTIAL_HANDOFF = (PROMPTS / "partial_handoff.txt").read_text(encoding="utf-8").strip()


def check_citations(answer: str, chunks: list[RetrievedChunk]) -> tuple[str, list[CitationRecord]]:
    valid_numbers = set(range(1, len(chunks) + 1))
    seen: set[int] = set()

    def replace(match: re.Match[str]) -> str:
        number = int(match.group(1))
        if number not in valid_numbers:
            return ""
        seen.add(number)
        return match.group(0)

    cleaned = re.sub(r"\s+([,.!?;:])", r"\1", CITATION.sub(replace, answer)).strip()
    citations = [
        CitationRecord(
            n=number,
            chunk_id=chunks[number - 1].chunk_id,
            section_id=chunks[number - 1].section_id,
            heading_path=chunks[number - 1].heading_path,
        )
        for number in sorted(seen)
    ]
    return cleaned, citations


def whole_reply(
    state: ConversationState, paragraphs: list[str], trace: list[str]
) -> dict[str, Any]:
    answer, citations = check_citations("\n\n".join(paragraphs), state.retrieval)
    return {
        "answer": answer,
        "messages": [AIMessage(content=answer)],
        "citations": [citation.model_dump() for citation in citations],
        "trace": trace,
        "answer_status": "answered",
        "coverage": state.coverage,
    }


def multipart_reply(
    state: ConversationState, paragraphs: list[str], trace: list[str]
) -> dict[str, Any]:
    update = whole_reply(state, paragraphs, trace)
    failed = [part for part in state.parts if not part.answered]
    if not failed:
        return {**update, "parts": state.parts}

    names = ", ".join(f"“{' '.join(CITATION.sub('', part.text).split())}”" for part in failed)
    summary = _PARTIAL_HANDOFF.format(questions=names)
    remaining = iter(mark_parts_handed_off(failed, HandoffReason.UNSUPPORTED_PART))
    parts = [part if part.answered else next(remaining) for part in state.parts]
    handoff = make_handoff(
        state.model_copy(update={"parts": parts}),
        HandoffReason.UNSUPPORTED_PART,
        customer_message=summary,
    )
    answer = f"{update['answer']}\n\n{summary}"
    return {
        **update,
        **handoff,
        "answer": answer,
        "messages": [AIMessage(content=answer)],
        "trace": [*trace, "handoff"],
        "answer_status": "partial",
        "parts": parts,
    }
