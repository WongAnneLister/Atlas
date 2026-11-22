"""Translate chunk metadata to and from the scalar fields stored in Milvus."""

from typing import Any

from support_agent.retrieval.chunking import Chunk
from support_agent.retrieval.filters import decode_day, encode_day

METADATA_STRINGS = ("doc_type", "topic", "product_category", "region")
DATE_FIELDS = ("effective_from", "effective_to")
DAY_FIELDS = ("effective_from_day", "effective_to_day")
METADATA_FIELDS = (*METADATA_STRINGS, *DAY_FIELDS)
LEGACY_CHUNK_FIELDS = tuple(
    field for field in Chunk.model_fields if field not in (*METADATA_STRINGS, *DATE_FIELDS)
)


def chunk_to_row(chunk: Chunk, open_end: int) -> dict[str, Any]:
    if chunk.effective_from is None:
        raise ValueError(f"Missing section metadata for {chunk.section_id}; run make data-docs")
    return {
        **chunk.model_dump(exclude=set(DATE_FIELDS)),
        "effective_from_day": encode_day(chunk.effective_from),
        "effective_to_day": encode_day(chunk.effective_to)
        if chunk.effective_to is not None
        else open_end,
    }


def row_to_chunk_fields(row: dict[str, Any], open_end: int) -> dict[str, Any]:
    if "effective_from_day" not in row:
        return row
    fields = dict(row)
    fields["effective_from"] = decode_day(fields.pop("effective_from_day"))
    last_day = fields.pop("effective_to_day")
    fields["effective_to"] = None if last_day == open_end else decode_day(last_day)
    return fields
