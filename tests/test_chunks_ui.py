"""Offline tests for the /chunks viewer page and read-only chunk inspection endpoints."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from test_api import client

_CATALOG_MD = """---
built_at: '2026-11-28'
doc_id: catalog_air_fryers
source_datasets:
- philips_manuals
title: Catalog Air Fryers
---

## Philips HD928X
<!-- section: product.HD928X -->

Intro safety text. Keep away from water. Clean after cooling down. Store in a dry place.
"""

_POLICY_MD = """---
built_at: '2026-11-28'
doc_id: returns
source_datasets:
- maktek_faqs
title: Returns
---

## General Returns
<!-- section: returns.maktek_faqs.general -->

Regarding “Can I return?”
You may return items within 30 days. Unused items qualify for a full refund.
"""


def _write_fixture(processed: Path) -> None:
    docs_dir = processed / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "catalog_air_fryers.md").write_text(_CATALOG_MD, encoding="utf-8")
    (docs_dir / "returns.md").write_text(_POLICY_MD, encoding="utf-8")

    # Build A (older): whole oversized product chunk.
    build_old = processed / "builds" / "aaaa1111bbbb2222"
    build_old.mkdir(parents=True, exist_ok=True)
    old_rows = [
        {
            "chunk_id": "old-hd928x-0",
            "doc_id": "catalog_air_fryers",
            "section_id": "product.HD928X",
            "title": "Catalog Air Fryers",
            "heading_path": "Catalog Air Fryers > Philips HD928X",
            "text": (
                "Intro safety text. Keep away from water. "
                "Clean after cooling down. Store in a dry place."
            ),
            "n_tokens": 5000,
            "doc_type": "catalog",
            "product_category": "air_fryers",
        }
    ]
    old_path = build_old / "chunks.jsonl"
    old_path.write_text("\n".join(json.dumps(r) for r in old_rows) + "\n", encoding="utf-8")
    os.utime(old_path, (1_700_000_000, 1_700_000_000))

    # Build B (newer): headed overlapping product windows + FAQ split.
    build_new = processed / "builds" / "cccc3333dddd4444"
    build_new.mkdir(parents=True, exist_ok=True)
    new_rows = [
        {
            "chunk_id": "new-hd928x-0",
            "doc_id": "catalog_air_fryers",
            "section_id": "product.HD928X",
            "title": "Catalog Air Fryers",
            "heading_path": "Catalog Air Fryers > Philips HD928X",
            "text": (
                "Philips HD928X\n\n"
                "Intro safety text. Keep away from water. Clean after cooling down."
            ),
            "n_tokens": 480,
            "doc_type": "catalog",
            "product_category": "air_fryers",
        },
        {
            "chunk_id": "new-hd928x-1",
            "doc_id": "catalog_air_fryers",
            "section_id": "product.HD928X",
            "title": "Catalog Air Fryers",
            "heading_path": "Catalog Air Fryers > Philips HD928X",
            "text": (
                "Philips HD928X\n\n"
                "Keep away from water. Clean after cooling down. Store in a dry place."
            ),
            "n_tokens": 490,
            "doc_type": "catalog",
            "product_category": "air_fryers",
        },
        {
            "chunk_id": "new-ret-0",
            "doc_id": "returns",
            "section_id": "returns.maktek_faqs.general",
            "title": "Returns",
            "heading_path": "Returns > General Returns",
            "text": "Regarding “Can I return?”\n\nYou may return items within 30 days.",
            "n_tokens": 120,
            "doc_type": "policy",
            "topic": "returns",
        },
    ]
    new_path = build_new / "chunks.jsonl"
    new_path.write_text("\n".join(json.dumps(r) for r in new_rows) + "\n", encoding="utf-8")
    os.utime(new_path, (1_800_000_000, 1_800_000_000))


async def test_chunks_page_and_empty_snapshots(seeded: Any, tmp_path: Path) -> None:
    settings, _ = seeded
    settings.data.processed_dir = str(tmp_path / "missing")
    async with client(seeded, customer_id=None) as api:
        page = await api.get("/chunks")
        assert page.status_code == 200
        assert "snapshot-select" in page.text

        snaps = await api.get("/api/chunks/snapshots")
        assert snaps.status_code == 200
        payload = snaps.json()
        assert payload["default_snapshot_id"] is None
        assert payload["snapshots"] == []

        docs = await api.get("/api/chunks/docs")
        assert docs.status_code == 404


async def test_chunks_snapshots_docs_and_overlap_spans(seeded: Any, tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    _write_fixture(processed)
    settings, _ = seeded
    settings.data.processed_dir = str(processed)

    async with client(seeded, customer_id=None) as api:
        snaps_resp = await api.get("/api/chunks/snapshots")
        assert snaps_resp.status_code == 200
        snaps = snaps_resp.json()
        assert snaps["default_snapshot_id"] == "build:cccc3333dddd4444"
        assert [s["snapshot_id"] for s in snaps["snapshots"]] == [
            "build:cccc3333dddd4444",
            "build:aaaa1111bbbb2222",
        ]
        # Older snapshot reports the >4096 hard-cap chunk.
        old_snap = snaps["snapshots"][1]
        assert old_snap["max_tokens"] == 5000
        assert old_snap["over_hard_cap"] == 1

        # Default snapshot doc list.
        docs_resp = await api.get("/api/chunks/docs")
        assert docs_resp.status_code == 200
        docs = {d["doc_id"]: d for d in docs_resp.json()["docs"]}
        assert set(docs) == {"catalog_air_fryers", "returns"}
        assert docs["catalog_air_fryers"]["chunk_count"] == 2
        assert docs["catalog_air_fryers"]["doc_type"] == "catalog"

        # Headed overlapping manual chunks map cleanly onto section prose.
        detail_resp = await api.get("/api/chunks/docs/catalog_air_fryers")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        prose = detail["sections"][0]["prose"]
        c0, c1 = detail["chunks"]

        assert c0["header_prefix"] == "Philips HD928X"
        assert c1["header_prefix"] == "Philips HD928X"
        assert prose[c0["span_start"] : c0["span_end"]] == c0["body_text"]
        assert prose[c1["span_start"] : c1["span_end"]] == c1["body_text"]
        assert c0["overlap_next_start"] == c1["overlap_prev_start"]
        assert c0["overlap_next_end"] == c1["overlap_prev_end"]
        overlap = prose[c1["overlap_prev_start"] : c1["overlap_prev_end"]]
        assert overlap == "Keep away from water. Clean after cooling down."

        # FAQ split prefix strips cleanly and matches body text.
        ret_resp = await api.get("/api/chunks/docs/returns")
        assert ret_resp.status_code == 200
        ret = ret_resp.json()
        rc = ret["chunks"][0]
        assert rc["header_prefix"] == "Regarding “Can I return?”"
        assert ret["sections"][0]["prose"][rc["span_start"] : rc["span_end"]] == rc["body_text"]

        # Switching to older build shows the 5000-token unheaded chunk.
        old_detail = await api.get(
            "/api/chunks/docs/catalog_air_fryers",
            params={"snapshot": "build:aaaa1111bbbb2222"},
        )
        assert old_detail.status_code == 200
        old_chunk = old_detail.json()["chunks"][0]
        assert old_chunk["n_tokens"] == 5000
        assert old_chunk["header_prefix"] == ""
        assert old_chunk["span_start"] == 0

        # Unknown snapshot / unknown doc / traversal return 404.
        bad_snap = await api.get("/api/chunks/docs", params={"snapshot": "../etc/passwd"})
        assert bad_snap.status_code == 404
        assert (await api.get("/api/chunks/docs/nonexistent")).status_code == 404
