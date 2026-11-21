"""Section-bounded source chunks with exact token counts and deterministic ids."""

from __future__ import annotations

import re
from bisect import bisect_right
from pathlib import Path

from pydantic import BaseModel, Field

from support_agent.config import ChunkSettings
from support_agent.data.doc_models import digest
from support_agent.data.validate_docs import parse_document
from support_agent.retrieval.tokenization import Tokenizer

CHUNKER_VERSION = "1"


class Chunk(BaseModel):
    chunk_id: str
    doc_id: str
    section_id: str
    title: str
    heading_path: str
    text: str = Field(min_length=1)
    n_tokens: int = Field(gt=0)


def split_text(text: str, tokenizer: Tokenizer, maximum: int, overlap: int) -> list[str]:
    if maximum <= 0 or not 0 <= overlap < maximum:
        raise ValueError("Need a positive token budget and a smaller nonnegative overlap")
    spans = tokenizer.spans(text)
    if not spans:
        return []
    ends = [end for _, end in spans]
    paragraphs = [match.end() for match in re.finditer(r"\n\s*\n", text)]
    sentences = [match.end() for match in re.finditer(r"(?<=[.!?])\s+", text)]
    result: list[str] = []
    start = 0
    while start < len(spans):
        end = min(start + maximum, len(spans))
        if end < len(spans):
            for boundaries in (paragraphs, sentences):
                possible = [
                    bisect_right(ends, boundary)
                    for boundary in boundaries
                    if start + overlap < bisect_right(ends, boundary) <= end
                ]
                if possible:
                    end = max(possible)
                    break
        piece = text[spans[start][0] : spans[end - 1][1]]
        # Subword tokens may change at a sliced boundary. Enforce the measured limit too.
        while tokenizer.count(piece) > maximum and end > start + 1:
            end -= 1
            piece = text[spans[start][0] : spans[end - 1][1]]
        if tokenizer.count(piece) > maximum:
            raise ValueError("A source token cannot fit the configured token budget")
        result.append(piece)
        if end == len(spans):
            break
        start = max(start + 1, end - overlap)
    return result


_FAQ_START = re.compile(r"(?=^Regarding “)", re.M)


def faq_units(prose: str) -> list[str]:
    """Split a section into its FAQ blocks; text before the first block stays a unit."""
    return [unit.strip() for unit in _FAQ_START.split(prose) if unit.strip()]


def section_pieces(
    sid: str, prose: str, config: ChunkSettings, tokenizer: Tokenizer, heading: str = ""
) -> list[str]:
    """Cut one section according to the configured strategy."""
    is_product = sid.startswith("product.")
    if config.strategy == "token":
        if is_product:
            return [prose]
        return split_text(prose, tokenizer, config.max_tokens, config.overlap_tokens)
    if is_product:
        header = heading if config.product_window_header and heading else ""
        budget = config.product_window_tokens - (tokenizer.count(header) + 2 if header else 0)
        if budget <= config.product_overlap_tokens:
            raise ValueError("A product heading leaves no room for its manual window")
        windows = split_text(prose, tokenizer, budget, config.product_overlap_tokens)
        return [f"{header}\n\n{window}" if header else window for window in windows]
    pieces: list[str] = []
    for unit in faq_units(prose):
        if tokenizer.count(unit) <= config.max_tokens:
            pieces.append(unit)
            continue
        # A long answer is split; every part repeats the question line so it stays findable.
        question, _, body = (
            unit.partition("\n") if unit.startswith("Regarding “") else ("", "", unit)
        )
        budget = config.max_tokens - (tokenizer.count(question) + 2 if question else 0)
        if budget <= config.overlap_tokens:
            raise ValueError("A FAQ question line leaves no room for its answer in one chunk")
        for part in split_text(body.strip(), tokenizer, budget, config.overlap_tokens):
            pieces.append(f"{question}\n\n{part}" if question else part)
    return pieces


def chunk_document(text: str, config: ChunkSettings, tokenizer: Tokenizer) -> list[Chunk]:
    sections, header = parse_document(text)
    headings = {
        sid: heading.strip()
        for heading, sid in re.findall(
            r"^## ([^\n]+)\n<!-- section: ([^\n]+) -->",
            text,
            re.M,
        )
    }
    return [
        chunk
        for sid, prose in sections.items()
        for chunk in chunk_section(
            sid, prose, header.doc_id, header.title, headings[sid], config, tokenizer
        )
    ]


def chunk_section(
    sid: str,
    prose: str,
    doc_id: str,
    title: str,
    heading: str,
    config: ChunkSettings,
    tokenizer: Tokenizer,
) -> list[Chunk]:
    return [
        Chunk(
            chunk_id=digest(f"{sid}:{index}"),
            doc_id=doc_id,
            section_id=sid,
            title=title,
            heading_path=f"{title} > {heading}",
            text=piece,
            n_tokens=tokenizer.count(piece),
        )
        for index, piece in enumerate(section_pieces(sid, prose, config, tokenizer, heading))
    ]


def load_chunks(folder: Path, config: ChunkSettings, tokenizer: Tokenizer) -> list[Chunk]:
    chunks = [
        chunk
        for path in sorted(folder.glob("*.md"))
        for chunk in chunk_document(
            path.read_text(encoding="utf-8"),
            config,
            tokenizer,
        )
    ]
    if not chunks:
        raise ValueError("No chunks found; run make data-docs")
    if len({chunk.chunk_id for chunk in chunks}) != len(chunks):
        raise ValueError("Duplicate section ids across source documents")
    return chunks


def embedding_text(chunk: Chunk, config: ChunkSettings) -> str:
    return f"{chunk.heading_path}\n\n{chunk.text}" if config.prepend_heading else chunk.text
