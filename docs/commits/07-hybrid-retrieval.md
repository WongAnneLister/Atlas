# Commit 07 — Hybrid retrieval with Reciprocal Rank Fusion

**Week 2 · depends on: 06**

## Context
Dense search understands paraphrases ("wanna send my stuff back"); BM25 nails exact tokens ("W40", "30 days").
We run both, take the top 50 from each, and fuse with RRF (k = 60). Scores from the two retrievers are on different scales,
which is why we fuse **ranks**, not scores.

## Read first
- `docs/RETRIEVAL.md`
- `src/support_agent/retrieval/milvus_store.py`, `embed.py`
- `configs/default.yaml` → `retrieval`

## Task
1. `src/support_agent/retrieval/types.py` — `RetrievedChunk` (chunk fields + `scores: dict[str, float]`, `ranks: dict[str, int]`), and a `Retriever` protocol: `retrieve(query: str, top_k: int) -> list[RetrievedChunk]`.
2. `src/support_agent/retrieval/dense.py` — `DenseRetriever` (embeds query with BGE-M3, Milvus vector search).
3. `src/support_agent/retrieval/bm25.py` — `Bm25Retriever` (Milvus full-text search on the sparse BM25 field).
4. `src/support_agent/retrieval/fusion.py` — pure function `rrf(rank_lists: dict[str, list[str]], k: int) -> list[tuple[str, float]]`; score = Σ 1/(k + rank), rank starting at 1. Ties broken by best single rank, then chunk_id (deterministic).
5. `src/support_agent/retrieval/hybrid.py` — `HybridRetriever` running dense and BM25 (concurrently is nice, not required), fusing with `rrf`, returning top_k with both component ranks kept in `ranks` for debugging.
6. `src/support_agent/retrieval/factory.py` — `build_retriever(mode: Literal["dense","bm25","hybrid","hybrid_rerank"])`. `hybrid_rerank` raises `NotImplementedError` until commit 08.
7. `scripts/search.py` + `make search Q="..." MODE=hybrid` — prints the top results with section id, ranks and scores. Handy for debugging and the demo.
8. Add a section "Hybrid + RRF" to `docs/RETRIEVAL.md` explaining why RRF and why k = 60 (standard default from the original paper; we may sweep it later).

## Requirements
- `rrf` has no I/O and no Milvus import.
- All top-k values and `rrf_k` come from config.
- Model-number queries: add a small normaliser (e.g. "w-40" → "W40", case-folding) applied to the BM25 query only, behind a config flag. Note it in RETRIEVAL.md; commit 08 will measure it.

## Tests
- `rrf` on hand-made lists: an item ranked 1 in one list and absent in the other; ties; k changes the order as expected.
- `HybridRetriever` with two fake retrievers returns fused order and keeps component ranks.
- Normaliser cases.

## Out of scope
Reranker and metrics (08).

## Done when
- [ ] `make search Q="Does the W40 come with a charger?" MODE=hybrid` returns sensible results on a real index
- [ ] `make check` green; PROGRESS row 07 updated
- [ ] Interview note `docs/notes/07-hybrid-retrieval.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(retrieval): dense and BM25 retrievers fused with reciprocal rank fusion
```
