# Commit 11 — Evidence gate and the knowledge path (cited answers or handoff)

**Week 3 · depends on: 08, 09**

## Context
This is the core safety feature. For `product_question` and `policy_question`, the flow is fixed:
**retrieve → rerank → gate → (answer with citations) or (handoff)**. The gate runs **before** generation, so a weak-evidence
question never reaches the answer model. The threshold is **not** chosen here — commit 13 sweeps it. Until then use a
placeholder from config and mark it clearly as untuned.

## Read first
- `AGENTS.md` §5.2 and §6 (the 4 signals and default weights)
- `src/support_agent/retrieval/rerank.py`, `graph/handoff.py`
- `docs/RETRIEVAL.md` (look at the rerank score distribution if the report has it; if not, add a histogram to this commit's dev analysis)

## Task
1. `src/support_agent/gate/signals.py` — pure functions over a list of reranked chunks + the query:
   - `top_score` — top-1 sigmoid rerank score.
   - `good_count` — count of chunks with score ≥ `gate.good_evidence_min`, capped at 3, divided by 3.
   - `margin` — clip(top1 − top2, 0, 1); 1.0 if only one chunk.
   - `key_hit` — extract key terms from the query (model-number regex, numbers with units, and a small policy-noun list in config: refund, return, warranty, coupon, shipping…). Score = fraction of key terms found in the top 3 chunks' text (case-insensitive, normalised like the BM25 normaliser). No key terms → 1.0 (neutral) — document this choice.
2. `src/support_agent/gate/evidence.py` — `GateResult(score, signals, passed, threshold, reason)` and `evaluate(query, chunks, settings) -> GateResult`. Weighted sum with weights from config (validated to sum to 1). If `threshold` is null in config → raise unless `allow_untuned=True` is passed (tests and early runs), so we cannot silently ship an untuned gate.
3. `src/support_agent/graph/nodes/knowledge.py`:
   - `retrieve` node — always runs `hybrid_rerank` on `rewritten_query`; stores chunks in state.
   - `gate` node — calls `evaluate`; stores result.
   - Conditional edge: passed → `answer`; failed → handoff with reason `low_evidence` (payload includes the retrieval snapshot and gate signals).
   - `answer` node — `main` model with prompt `graph/prompts/answer.md`: answer only from the numbered sources; cite like `[1]`, `[2]` after each claim; if the sources do not cover part of the question, say which part and offer a human. Pass at most `rerank_top_k` chunks, each with its number, heading path and text.
   - Post-check: parse citations; drop citation numbers that do not exist; if the answer has **no** valid citation → replace with handoff (`low_evidence`). Store `citations` as `[{n, chunk_id, section_id, heading_path}]`.
4. Wire path B in `build.py`. The knowledge path must not have any edge that skips `gate`.
5. `eval/gate_dev_analysis.py` + `make gate-analysis` — on the **dev** split only: run retrieve+rerank+gate signals (no generation) and write `eval/reports/gate_signals_dev.md`: per-group distributions of each signal and the combined score (answerable vs no_answer), as a table and a PNG. This is input for commit 13; it does not pick a threshold.

## Requirements
- Signals are deterministic pure functions; unit-testable without models.
- The gate result is part of state and will be traced.

## Tests
- Each signal on hand-made chunk lists (including empty list → score 0, fail).
- Weights must sum to 1 (validator), `threshold=None` raises without `allow_untuned`.
- Graph: with a fake reranker giving high scores → trace `retrieve → gate → answer`; low scores → `retrieve → gate → handoff`, and **zero calls** to the answer model (assert on the fake).
- Citation post-check: invalid `[7]` dropped; answer with no citations → handoff.

## Out of scope
Threshold choice and end-to-end metrics (13). Query decomposition and partial answers (24).

## Done when
- [ ] `make gate-analysis` writes the dev distributions report
- [ ] A manual chat shows a cited answer for "How long do I have to return an item?" and a handoff for "Can I pay with gold bars?" (with `allow_untuned` and a placeholder threshold — say which)
- [ ] `make check` green; PROGRESS row 11 updated
- [ ] Interview note `docs/notes/11-evidence-gate.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(gate): four-signal evidence gate before generation and cited knowledge-answer path
```
