"""Read-only loader for local processed documents and chunk snapshots."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from support_agent.config import REPO_ROOT, ChunkSettings, Settings
from support_agent.data.section_metadata import SectionMetadata, load_section_metadata
from support_agent.data.validate_docs import parse_document

_HEADING_RE = re.compile(r"^## ([^\n]+)\n<!-- section: ([^\n]+) -->", re.M)


class ChunkLimits(BaseModel):
    max_tokens: int
    overlap_tokens: int
    product_whole_max_tokens: int
    hard_max_tokens: int


class SnapshotSummary(BaseModel):
    snapshot_id: str
    label: str
    kind: Literal["build", "file"]
    chunk_count: int
    doc_count: int
    section_count: int
    max_tokens: int
    over_max_tokens: int
    over_hard_cap: int
    modified_at: str


class DocSummary(BaseModel):
    doc_id: str
    title: str
    doc_type: str
    source_datasets: list[str]
    built_at: str
    section_count: int
    chunk_count: int
    max_chunk_tokens: int
    total_tokens: int
    over_max_tokens: int
    over_hard_cap: int


class ChunkView(BaseModel):
    chunk_id: str
    section_id: str
    section_index: int
    global_index: int
    heading_path: str
    text: str
    header_prefix: str
    body_text: str
    n_tokens: int
    doc_type: str
    topic: str
    product_category: str
    effective_from: str | None = None
    effective_to: str | None = None
    span_start: int | None = None
    span_end: int | None = None
    overlap_prev_start: int | None = None
    overlap_prev_end: int | None = None
    overlap_next_start: int | None = None
    overlap_next_end: int | None = None


class SectionView(BaseModel):
    section_id: str
    heading: str
    prose: str
    doc_type: str
    topic: str
    product_category: str
    effective_from: str | None = None
    effective_to: str | None = None
    chunk_count: int
    total_tokens: int
    max_chunk_tokens: int


class SnapshotsResponse(BaseModel):
    limits: ChunkLimits
    default_snapshot_id: str | None
    snapshots: list[SnapshotSummary]


class SnapshotDocsResponse(BaseModel):
    snapshot: SnapshotSummary
    limits: ChunkLimits
    docs: list[DocSummary]


class DocumentDetailResponse(BaseModel):
    snapshot: SnapshotSummary
    limits: ChunkLimits
    doc_id: str
    title: str
    built_at: str
    source_datasets: list[str]
    sections: list[SectionView]
    chunks: list[ChunkView]


class _ParsedDoc:
    def __init__(
        self,
        doc_id: str,
        title: str,
        built_at: str,
        source_datasets: list[str],
        sections: dict[str, str],
        headings: dict[str, str],
    ) -> None:
        self.doc_id = doc_id
        self.title = title
        self.built_at = built_at
        self.source_datasets = source_datasets
        self.sections = sections
        self.headings = headings


def _processed_dir(settings: Settings) -> Path:
    raw = Path(settings.data.processed_dir)
    return raw if raw.is_absolute() else REPO_ROOT / raw


def _limits(config: ChunkSettings) -> ChunkLimits:
    return ChunkLimits(
        max_tokens=config.max_tokens,
        overlap_tokens=config.overlap_tokens,
        product_whole_max_tokens=config.product_whole_max_tokens,
        hard_max_tokens=config.hard_max_tokens,
    )


def _discover_snapshot_files(processed: Path) -> list[tuple[str, Literal["build", "file"], Path]]:
    found: list[tuple[float, str, Literal["build", "file"], Path]] = []
    builds_dir = processed / "builds"
    if builds_dir.is_dir():
        for path in builds_dir.glob("*/chunks.jsonl"):
            if path.is_file():
                build_id = path.parent.name
                found.append((path.stat().st_mtime, f"build:{build_id}", "build", path))
    if processed.is_dir():
        for path in processed.glob("chunks*.jsonl"):
            if path.is_file():
                found.append((path.stat().st_mtime, f"file:{path.name}", "file", path))
    # Sort builds first (newest first), then standalone files (newest first).
    found.sort(key=lambda item: (0 if item[2] == "build" else 1, -item[0], item[1]))
    return [(sid, kind, path) for _, sid, kind, path in found]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                rows.append(json.loads(stripped))
    return rows


def _summarize_snapshot(
    snapshot_id: str,
    kind: Literal["build", "file"],
    path: Path,
    rows: list[dict[str, Any]],
    limits: ChunkLimits,
) -> SnapshotSummary:
    tokens = [int(row.get("n_tokens", 0)) for row in rows]
    max_tok = max(tokens, default=0)
    over_max = sum(1 for tok in tokens if tok > limits.max_tokens)
    over_hard = sum(1 for tok in tokens if tok > limits.hard_max_tokens)
    doc_ids = {str(row.get("doc_id", "")) for row in rows if row.get("doc_id")}
    sec_ids = {str(row.get("section_id", "")) for row in rows if row.get("section_id")}
    short_name = f"build {path.parent.name[:8]}" if kind == "build" else path.name
    label = f"{short_name} · {len(rows)} chunks · max {max_tok} tok"
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()
    return SnapshotSummary(
        snapshot_id=snapshot_id,
        label=label,
        kind=kind,
        chunk_count=len(rows),
        doc_count=len(doc_ids),
        section_count=len(sec_ids),
        max_tokens=max_tok,
        over_max_tokens=over_max,
        over_hard_cap=over_hard,
        modified_at=modified,
    )


def _resolve_snapshot(
    processed: Path, snapshot_id: str | None
) -> tuple[str, Literal["build", "file"], Path] | None:
    files = _discover_snapshot_files(processed)
    if not files:
        return None
    if snapshot_id is None:
        return files[0]
    for item in files:
        if item[0] == snapshot_id:
            return item
    return None


def _load_docs(docs_dir: Path) -> tuple[dict[str, _ParsedDoc], dict[str, SectionMetadata]]:
    docs: dict[str, _ParsedDoc] = {}
    if not docs_dir.is_dir():
        return docs, {}
    meta: dict[str, SectionMetadata] = {}
    meta_file = docs_dir / "section_metadata.json"
    if meta_file.is_file():
        meta = load_section_metadata(docs_dir)
    for path in sorted(docs_dir.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        sections, header = parse_document(raw)
        headings = {sid.strip(): heading.strip() for heading, sid in _HEADING_RE.findall(raw)}
        docs[header.doc_id] = _ParsedDoc(
            doc_id=header.doc_id,
            title=header.title,
            built_at=header.built_at,
            source_datasets=list(header.source_datasets),
            sections=sections,
            headings=headings,
        )
    return docs, meta


def _match_chunk_span(
    prose: str, text: str, heading: str, search_from: int
) -> tuple[str, str, int | None, int | None]:
    """Locate chunk text inside section prose, stripping any prepended heading or FAQ line."""
    # Direct match (unheaded chunk).
    pos = prose.find(text, search_from)
    if pos != -1:
        return "", text, pos, pos + len(text)
    if search_from > 0:
        pos = prose.find(text)
        if pos != -1:
            return "", text, pos, pos + len(text)

    # Product window heading prepended as "{heading}\n\n{window}".
    headed_prefix = f"{heading}\n\n"
    if heading and text.startswith(headed_prefix):
        body = text[len(headed_prefix) :]
        pos = prose.find(body, search_from)
        if pos == -1 and search_from > 0:
            pos = prose.find(body)
        return heading, body, (pos if pos != -1 else None), (pos + len(body) if pos != -1 else None)

    # Long FAQ split prepends "{question}\n\n{part}".
    if "\n\n" in text:
        prefix, _, body = text.partition("\n\n")
        pos = prose.find(body, search_from)
        if pos == -1 and search_from > 0:
            pos = prose.find(body)
        if pos != -1:
            return prefix, body, pos, pos + len(body)

    return "", text, None, None


def _as_str_date(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def list_snapshots(settings: Settings) -> SnapshotsResponse:
    processed = _processed_dir(settings)
    limits = _limits(settings.chunk)
    summaries: list[SnapshotSummary] = []
    for snapshot_id, kind, path in _discover_snapshot_files(processed):
        rows = _read_jsonl(path)
        summaries.append(_summarize_snapshot(snapshot_id, kind, path, rows, limits))
    return SnapshotsResponse(
        limits=limits,
        default_snapshot_id=summaries[0].snapshot_id if summaries else None,
        snapshots=summaries,
    )


def list_snapshot_docs(settings: Settings, snapshot_id: str | None) -> SnapshotDocsResponse:
    processed = _processed_dir(settings)
    limits = _limits(settings.chunk)
    resolved = _resolve_snapshot(processed, snapshot_id)
    if resolved is None:
        raise FileNotFoundError("Chunk snapshot not found")
    sid, kind, path = resolved
    rows = _read_jsonl(path)
    snapshot = _summarize_snapshot(sid, kind, path, rows, limits)
    parsed_docs, meta = _load_docs(processed / "docs")

    by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        doc_id = str(row.get("doc_id", ""))
        if doc_id:
            by_doc[doc_id].append(row)

    all_doc_ids = sorted(set(parsed_docs.keys()) | set(by_doc.keys()))
    doc_summaries: list[DocSummary] = []
    for doc_id in all_doc_ids:
        doc_rows = by_doc.get(doc_id, [])
        parsed = parsed_docs.get(doc_id)
        toks = [int(r.get("n_tokens", 0)) for r in doc_rows]
        doc_types = {
            str(
                r.get("doc_type")
                or (meta[r["section_id"]].doc_type if r.get("section_id") in meta else "")
            )
            for r in doc_rows
        } - {""}
        if not doc_types and parsed is not None:
            doc_types = {meta[s].doc_type for s in parsed.sections if s in meta}
        if not doc_types:
            dtype = "catalog" if doc_id.startswith("catalog_") else "policy"
        elif len(doc_types) == 1:
            dtype = next(iter(doc_types))
        else:
            dtype = "mixed"
        doc_title = (
            parsed.title
            if parsed
            else (str(doc_rows[0].get("title", doc_id)) if doc_rows else doc_id)
        )
        doc_summaries.append(
            DocSummary(
                doc_id=doc_id,
                title=doc_title,
                doc_type=dtype,
                source_datasets=parsed.source_datasets if parsed else [],
                built_at=parsed.built_at if parsed else "",
                section_count=(
                    len(parsed.sections)
                    if parsed
                    else len({str(r.get("section_id", "")) for r in doc_rows})
                ),
                chunk_count=len(doc_rows),
                max_chunk_tokens=max(toks, default=0),
                total_tokens=sum(toks),
                over_max_tokens=sum(1 for t in toks if t > limits.max_tokens),
                over_hard_cap=sum(1 for t in toks if t > limits.hard_max_tokens),
            )
        )
    return SnapshotDocsResponse(snapshot=snapshot, limits=limits, docs=doc_summaries)


def get_document_detail(
    settings: Settings, doc_id: str, snapshot_id: str | None
) -> DocumentDetailResponse:
    processed = _processed_dir(settings)
    limits = _limits(settings.chunk)
    resolved = _resolve_snapshot(processed, snapshot_id)
    if resolved is None:
        raise FileNotFoundError("Chunk snapshot not found")
    sid, kind, path = resolved
    rows = _read_jsonl(path)
    snapshot = _summarize_snapshot(sid, kind, path, rows, limits)
    parsed_docs, meta = _load_docs(processed / "docs")

    doc_rows = [row for row in rows if str(row.get("doc_id", "")) == doc_id]
    parsed = parsed_docs.get(doc_id)
    if parsed is None and not doc_rows:
        raise KeyError(f"Document not found: {doc_id}")

    rows_by_section: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in doc_rows:
        rows_by_section[str(row.get("section_id", ""))].append(row)

    section_order: list[str] = list(parsed.sections.keys()) if parsed else []
    for sec_id in rows_by_section:
        if sec_id not in section_order:
            section_order.append(sec_id)

    section_views: list[SectionView] = []
    chunk_views: list[ChunkView] = []

    for sec_id in section_order:
        prose = parsed.sections.get(sec_id, "") if parsed else ""
        heading = parsed.headings.get(sec_id, sec_id) if parsed else sec_id
        sec_meta = meta.get(sec_id)
        sec_rows = rows_by_section.get(sec_id, [])
        sec_chunks: list[ChunkView] = []
        cursor = 0

        for idx, row in enumerate(sec_rows):
            text = str(row.get("text", ""))
            prefix, body, start, end = (
                _match_chunk_span(prose, text, heading, cursor) if prose else ("", text, None, None)
            )
            if start is not None:
                cursor = start + 1
            view = ChunkView(
                chunk_id=str(row.get("chunk_id", "")),
                section_id=sec_id,
                section_index=idx,
                global_index=len(chunk_views) + len(sec_chunks),
                heading_path=str(row.get("heading_path", heading)),
                text=text,
                header_prefix=prefix,
                body_text=body,
                n_tokens=int(row.get("n_tokens", 0)),
                doc_type=str(row.get("doc_type") or (sec_meta.doc_type if sec_meta else "policy")),
                topic=str(row.get("topic") or (sec_meta.topic if sec_meta else "")),
                product_category=str(
                    row.get("product_category") or (sec_meta.product_category if sec_meta else "")
                ),
                effective_from=_as_str_date(
                    row.get("effective_from") or (sec_meta.effective_from if sec_meta else None)
                ),
                effective_to=_as_str_date(
                    row.get("effective_to") or (sec_meta.effective_to if sec_meta else None)
                ),
                span_start=start,
                span_end=end,
            )
            sec_chunks.append(view)

        # Compute exact character overlaps between consecutive chunks in this section.
        for idx in range(1, len(sec_chunks)):
            prev_c = sec_chunks[idx - 1]
            curr_c = sec_chunks[idx]
            if (
                prev_c.span_start is not None
                and prev_c.span_end is not None
                and curr_c.span_start is not None
                and curr_c.span_end is not None
                and curr_c.span_start < prev_c.span_end
            ):
                ov_start = max(prev_c.span_start, curr_c.span_start)
                ov_end = min(prev_c.span_end, curr_c.span_end)
                if ov_start < ov_end:
                    prev_c.overlap_next_start = ov_start
                    prev_c.overlap_next_end = ov_end
                    curr_c.overlap_prev_start = ov_start
                    curr_c.overlap_prev_end = ov_end

        chunk_views.extend(sec_chunks)
        toks = [c.n_tokens for c in sec_chunks]
        section_views.append(
            SectionView(
                section_id=sec_id,
                heading=heading,
                prose=prose,
                doc_type=(
                    sec_meta.doc_type
                    if sec_meta
                    else (sec_chunks[0].doc_type if sec_chunks else "policy")
                ),
                topic=(sec_meta.topic if sec_meta else (sec_chunks[0].topic if sec_chunks else "")),
                product_category=(
                    sec_meta.product_category
                    if sec_meta
                    else (sec_chunks[0].product_category if sec_chunks else "")
                ),
                effective_from=_as_str_date(
                    sec_meta.effective_from
                    if sec_meta
                    else (sec_chunks[0].effective_from if sec_chunks else None)
                ),
                effective_to=_as_str_date(
                    sec_meta.effective_to
                    if sec_meta
                    else (sec_chunks[0].effective_to if sec_chunks else None)
                ),
                chunk_count=len(sec_chunks),
                total_tokens=sum(toks),
                max_chunk_tokens=max(toks, default=0),
            )
        )

    title = (
        parsed.title if parsed else (str(doc_rows[0].get("title", doc_id)) if doc_rows else doc_id)
    )
    return DocumentDetailResponse(
        snapshot=snapshot,
        limits=limits,
        doc_id=doc_id,
        title=title,
        built_at=parsed.built_at if parsed else "",
        source_datasets=parsed.source_datasets if parsed else [],
        sections=section_views,
        chunks=chunk_views,
    )
