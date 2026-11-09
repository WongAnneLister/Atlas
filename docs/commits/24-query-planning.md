# Commit 24 — Query planning: decomposition, per-part gating, partial answers

**Phase 2 · RAG · depends on: 17, 23**

## Context
Cross-doc questions ("If I return an item bought with a coupon, do I get the coupon back, and who pays shipping?") have parts
that live in different sections. One retrieval for the whole question often finds only one part; one gate for the whole
question either blocks a half-answerable question or lets a half-unsupported one through. Fix: plan the query into parts,
retrieve and gate **each part**, and answer only the parts that passed — handing off the rest.

## Read first
- `eval/reports/retrieval.md` and `e2e.md` (look at `cross_doc` failures first and write down the pattern before coding)
- `graph/nodes/knowledge.py`, `gate/evidence.py`

## Task
1. `src/support_agent/graph/nodes/plan.py` — `fast` model with structured output: `{parts: [{text, key_terms}], is_multi_part}`. Rules in the prompt: max 3 parts, never invent parts, keep the user's own terms. Single-part questions skip planning cheaply (heuristic pre-check: conjunctions/question marks/length; LLM only if the heuristic says maybe).
2. Knowledge path becomes: `plan → (for each part: retrieve → rerank → gate) → merge → answer`. Use LangGraph `Send` (map) or a loop node; parts run concurrently.
3. **Per-part gate** with the same calibrated threshold. Outcomes:
   - all parts pass → full answer;
   - some pass → **partial answer**: answer the passed parts with citations and clearly say which part needs a human; create a handoff with only the failed parts;
   - none pass → handoff (as v1).
   Partial answers are behind config `knowledge.partial_answers` (default on) so we can compare.
4. Answer prompt gets sources grouped by part; citations still numbered globally.
5. **Metrics** (extend eval):
   - `full_answer_rate` on `cross_doc` (all gold parts answered with valid citations),
   - `part_recall@5` (each part's gold section retrieved for that part),
   - partial-answer correctness (judge + human sample): answered parts correct, unanswered parts truly unsupported,
   - no-answer false-accept (must stay 0 — a no-answer question split into parts must not sneak through).
6. Report v1 vs planning vs planning+partial on all groups with paired CIs. Watch cost and latency (extra LLM call): report both.

## Requirements
- No change for single-part questions beyond the heuristic check (latency for them must not go up significantly).
- The planner cannot add parts that are not in the user's question (check: each part's key terms appear in the original or rewritten query; otherwise drop the part and log it).

## Tests
- Heuristic pre-check on fixtures.
- Planner output validation drops invented parts.
- Graph with fakes: 2 parts, one passes → partial answer + handoff payload contains only the failed part.
- All parts fail → handoff, zero answer-model calls.

## Out of scope
Per-intent thresholds (consider only if the data asks for it; log as follow-up).

## Done when
- [ ] Report shows cross_doc full-answer rate before/after with CIs, false-accept still 0, latency/cost deltas
- [ ] `make check` green; PROGRESS row 24 updated
- [ ] Interview note `docs/notes/24-query-planning.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(rag): query planning with per-part retrieval and gating, and partial answers with targeted handoff
```
