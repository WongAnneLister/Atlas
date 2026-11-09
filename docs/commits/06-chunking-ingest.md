# Commit 06 — Chunking, BGE-M3 embeddings, Milvus ingestion

**Week 2 · depends on: 03 (and Milvus from 01)**

## Context
Policy docs and the catalog must go into one Milvus collection that supports **both** dense vector search (BGE-M3, 1024 dims)
and BM25 full-text search (Milvus ≥ 2.5 built-in BM25 function on a sparse field). Chunks must keep their section id so
retrieval can be scored against the eval set's `gold_sections`.

## Read first
- `AGENTS.md` §2, §3, §5.4
- `configs/default.yaml` → `retrieval`, `milvus`
- A couple of files in `data/processed/docs/` to see the section markers

## Task
1. `src/support_agent/retrieval/chunking.py`:
   - Split each doc by `##` sections first (never cross a section boundary). If a section is longer than `chunk.max_tokens` (config, default 512), split by paragraph, then by sentence, with `chunk.overlap_tokens` (default 64).
   - Product sections are always one chunk.
   - `Chunk` model: `chunk_id` (stable hash of section_id + index), `doc_id`, `section_id`, `title`, `heading_path` (e.g. "Returns > Return window"), `text`, `n_tokens`.
   - Prepend `heading_path` to the text that gets embedded (not to the text shown to users). Make this a config flag so we can measure it later.
2. `src/support_agent/retrieval/embed.py` — `Embedder` protocol + `BgeM3Embedder` (batching, normalisation, device from config) + `FakeEmbedder` for tests (deterministic hash → vector).
3. `src/support_agent/retrieval/milvus_store.py`:
   - Collection schema: `chunk_id` (pk, varchar), `doc_id`, `section_id`, `heading_path`, `text` (varchar, analyzer enabled), `dense` (float vector 1024, COSINE, HNSW), `sparse` (sparse float vector produced by a BM25 `Function` from `text`).
   - `create_or_reset()`, `upsert(chunks, vectors)`, `count()`.
   - Index params from config.
4. `src/support_agent/ingest.py` + `make ingest` — load docs → chunk → embed → upsert. Print counts and timing. Write `data/processed/chunks.jsonl` for inspection.
5. `docs/RETRIEVAL.md` — first section "Chunking & index": the rules above and the real counts (chunks, avg/max tokens).

## Requirements
- Re-running `make ingest` gives the same chunk ids.
- The embedding model downloads once to a cache dir from config; never commit weights.
- Milvus code is isolated behind `milvus_store.py`; nothing else imports `pymilvus`.

## Tests
- Chunking: never crosses sections; long section split with overlap; product section stays whole; ids stable.
- `FakeEmbedder` determinism.
- Milvus store: `@pytest.mark.integration` test that creates a temp collection, inserts 5 chunks, and gets them back via dense and BM25 search.

## Out of scope
Hybrid fusion (07), rerank (08).

## Done when
- [ ] `make up && make ingest` loads all chunks; counts printed and written to `docs/RETRIEVAL.md`
- [ ] `make check` green (integration test run manually and result noted)
- [ ] PROGRESS row 06 updated
- [ ] Interview note `docs/notes/06-chunking-ingest.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(retrieval): section-aware chunking, BGE-M3 embeddings and Milvus dense+BM25 collection
```
