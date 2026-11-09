# Commit 08 — Cross-encoder rerank and the 4-config retrieval experiment

**Week 2 · depends on: 05, 07**

## Context
A cross-encoder reads the query and each candidate together, so it ranks much better than either retriever alone, but it is slow —
so we only rerank the fused candidates and keep the top 5. This commit also produces the first required experiment:
**dense vs BM25 vs hybrid vs hybrid + rerank** on the eval set. This is the Week 2 checkpoint.

## Read first
- `docs/PRD.md` → Evaluation (metrics, required experiments)
- `AGENTS.md` §5.1
- `eval/schema.py`, `src/support_agent/retrieval/*`

## Task
1. `src/support_agent/retrieval/rerank.py` — `Reranker` protocol + `BgeReranker` (cross-encoder from config, batched, returns raw logits **and** sigmoid scores) + `FakeReranker` for tests.
   `RerankingRetriever(base, reranker, candidates_k, top_k)` wraps any retriever. Store `scores["rerank"]` (sigmoid) and `scores["rerank_logit"]`.
   Wire `hybrid_rerank` in the factory.
2. `eval/metrics.py` — pure functions: `recall_at_k(ranked_section_ids, gold, k)`, `mrr(...)`, `hit_all_at_k` (for cross_doc: all gold sections in top k). Section-level matching (a chunk counts if its `section_id` ∈ gold).
3. `eval/retrieval_eval.py` + `make eval-retrieval`:
   - Runs the 4 modes over the **answerable** items (240) on `--split dev|test|all` (default `test`, and always also writes `dev`).
   - Metrics per mode, overall and per group: Recall@1/3/5, MRR, cross_doc hit_all@5, mean latency per query.
   - Writes `eval/reports/retrieval.md` (tables + a 3-line "what this means" summary) and `eval/reports/retrieval_<split>.csv` (per-question ranks for every mode, so misses can be inspected).
   - Header records git SHA, config hash, model names, eval file hash, date, split (see AGENTS §5.1).
   - Caches retrieval results per (mode, config hash, question) under `.cache/` to save time and API cost.
4. `eval/failures.py` + `make eval-failures MODE=hybrid_rerank` — prints the misses with the question, gold section and the top 5 retrieved headings.
5. Also run two small ablations behind flags and add them to the report: heading-path prefix on/off (from 06), model-number normaliser on/off (from 07). Each as one extra row.

## Requirements
- Numbers in `docs/RETRIEVAL.md` are copied from `eval/reports/retrieval.md` with the report path. Never written by hand.
- If Recall@5 on test is below the PRD target (95%), **do not tune on test**. Look at dev failures, write the top 3 failure patterns in RETRIEVAL.md, and stop. Fixes are separate commits.

## Tests
- Metrics on hand-made rankings (including cross_doc partial hits and no gold in list).
- `RerankingRetriever` with fakes reorders correctly and keeps only top_k.
- Report writer produces the header fields.

## Out of scope
Evidence gate (11). Changing the eval set.

## Done when
- [ ] `make eval-retrieval` writes the report with all 4 modes + 2 ablations on dev and test
- [ ] `docs/RETRIEVAL.md` has the comparison table and failure patterns
- [ ] `make check` green; PROGRESS row 08 updated with test Recall@5 and MRR for each mode
- [ ] **Checkpoint 2**: mark "Week 2 gate passed — 4 configs measured" in PROGRESS
- [ ] Interview note `docs/notes/08-rerank-retrieval-eval.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(retrieval): cross-encoder rerank and 4-config retrieval evaluation report
```
