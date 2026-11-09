# Commit 22 — Incremental ingestion, versioned index, eval-gated alias switch

**Phase 2 · RAG · depends on: 17, 18**

## Context
v1 rebuilds the whole collection on every `make ingest`. In production, docs change a few sections at a time, embedding models
get upgraded, and a bad index must never go live. This commit adds: change detection per section, versioned collections,
an alias that the app reads, and a release step that **runs the retrieval eval before switching the alias**, with rollback.

## Read first
- `docs/RETRIEVAL.md`, `src/support_agent/retrieval/*`, `ingest.py`
- Milvus alias docs (`create_alias` / `alter_alias`) for the installed pymilvus

## Task
1. **Doc store of record** — Postgres tables (migration): `documents(doc_id, title, source, version, updated_at)`, `sections(section_id, doc_id, content_hash, text, metadata jsonb, version, is_deleted)`, `index_builds(build_id, collection, embed_model, chunker_version, created_at, status, eval_run_id)`.
2. **Change detection** — `ingest.py --incremental`: compare section content hashes with the DB; produce a plan `{added, changed, deleted, unchanged}`; print it (`--dry-run`).
3. **Two modes**
   - *In-place incremental* (same embed model + chunker version): upsert changed/added chunks, delete removed ones (by `section_id`) in the live collection; record a build row.
   - *Full rebuild* (model or chunker version changed): build a **new collection** `support_chunks_<build_id>`, then release it via step 4.
4. **Release with eval gate** — `make index-release BUILD=<id>`: run retrieval eval (dev + smoke test) against the new collection; compare to the current live build with the eval platform; if not `worse` → `alter_alias("support_chunks_live", new)`; else refuse and print why. `make index-rollback` moves the alias back to the previous build. Keep the last 2 builds; GC older ones.
5. The app and evals read **only** the alias. Cache keys from commit 26 will include `build_id`, so expose `current_build_id()`.
6. **Freshness test** — a script edits one policy section (fixture change, e.g. return window 30 → 45 days), runs incremental ingest, and asks the question; the answer must cite the new text. Add it as an integration test.
7. `docs/RETRIEVAL.md` → new section "Index lifecycle" with a diagram of build → eval → alias switch → rollback.

## Requirements
- Incremental ingest of a 1-section change touches only that section's chunks (assert counts).
- Deleted sections disappear from search immediately after ingest.
- Chunk ids stay stable for unchanged sections.

## Tests
- Change-plan computation on fixtures (add/change/delete/unchanged).
- Release refuses when the fake eval returns `worse`; switches when `no significant change`/`better`.
- Rollback restores the previous alias target.
- Integration: freshness test against Milvus + Postgres.

## Out of scope
Policy validity dates (23).

## Done when
- [ ] Freshness test passes; release and rollback demonstrated (note in PROGRESS)
- [ ] `make check` green; PROGRESS row 22 updated
- [ ] Interview note `docs/notes/22-incremental-ingestion.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(retrieval): incremental ingestion with change detection, versioned collections and eval-gated alias release
```
