# Commit 23 — Policy versions by date and metadata-filtered retrieval

**Phase 2 · RAG · depends on: 22**

## Context
Real policies change over time, and a refund must be judged by the policy **in force when the order was placed**, not today's.
Product questions should also search only the relevant catalog category when we know it. This commit adds validity dates
and metadata filters to retrieval, plus eval items that only pass if the filter is right.

## Read first
- `docs/RETRIEVAL.md` (index lifecycle), `graph/nodes/refund/`, `graph/nodes/knowledge.py`
- `data/processed/docs/` (front matter and section markers)

## Task
1. **Metadata model** — sections get `doc_type` (`policy | catalog`), `topic`, `product_category` (catalog), `effective_from`, `effective_to` (nullable), `region` (default `global`). Stored in Postgres `sections.metadata` and as Milvus scalar fields (with indexes where useful).
2. **Policy versions fixture** — create a second version of 2–3 policy sections with different rules and dates (e.g. return window 30 days before `2026-06-01`, 45 days after; coupon refund rule change). Clearly marked as **synthetic** in `docs/DOCS_BUILD.md`. Seed orders on both sides of the change date.
3. **Filtered retrieval** — `Retriever.retrieve(query, top_k, filters: RetrievalFilters | None)`; filters become Milvus boolean expressions applied to **both** dense and BM25 searches before fusion.
   - Knowledge path: default filter `effective_from <= today AND (effective_to IS NULL OR effective_to > today)`; if the query names a product model or category, add `product_category`.
   - Refund path: filter by the **order date** instead of today.
4. **Answer transparency** — when the applicable policy is not the current one, the answer says so ("Your order was placed on …, so the policy that applied then is …") with the citation.
5. **Eval** — add `eval/sets/eval_v2.jsonl` = v1 + a new group `time_sensitive` (≥ 40 items: same question with different order dates / "current policy" phrasing) registered as a new version. Gold sections depend on the date. Run before/after with `make eval-compare`.
6. Ablation: no filter vs filter vs filter + category boost — add to `eval/reports/retrieval.md`.

## Requirements
- Filters never widen results: if a filtered search returns nothing, the gate fails → handoff (do not silently drop the filter).
- `eval_v1` metrics must not get worse (paired compare).

## Tests
- Filter-expression builder for each combination (pure function).
- Refund path uses the order date (fake retriever records the filters it got).
- Empty filtered result → handoff, zero answer-model calls.

## Out of scope
Multi-region policies (only the field exists).

## Done when
- [ ] `time_sensitive` group results with CIs; v1 no regression
- [ ] `make check` green; PROGRESS row 23 updated
- [ ] Interview note `docs/notes/23-policy-versions-metadata.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(retrieval): policy validity dates and metadata-filtered hybrid retrieval with time-sensitive eval group
```
