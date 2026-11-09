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
    chunks: list[Chunk] = []
    for sid, prose in sections.items():
        pieces = (
            [prose]
            if sid.startswith("product.")
            else split_text(
                prose,
                tokenizer,
                config.max_tokens,
                config.overlap_tokens,
            )
        )
        for index, piece in enumerate(pieces):
            chunks.append(
                Chunk(
                    chunk_id=digest(f"{sid}:{index}"),
                    doc_id=header.doc_id,
                    section_id=sid,
                    title=header.title,
                    heading_path=f"{header.title} > {headings[sid]}",
                    text=piece,
                    n_tokens=tokenizer.count(piece),
                )
            )
    return chunks


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
