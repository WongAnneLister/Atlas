# Commit 25 — Claim-level grounding check after generation

**Phase 2 · RAG · depends on: 17, 24**

## Context
The pre-generation gate stops questions with weak evidence, but the model can still add one unsupported sentence to an
otherwise good answer (a number, a promise, a detail from training data). This commit adds a **post-generation check at the
claim level**: split the answer into claims, verify each against its cited sources, and remove or fix unsupported ones.
The gate decides *whether* to answer; this decides *what* may be said.

## Read first
- `eval/reports/judge_calibration.md`, the hallucination review CSV (what kinds of errors occurred)
- `graph/nodes/knowledge.py` (citation post-check), `eval/judge.py`

## Task
1. `src/support_agent/grounding/claims.py` — split the answer into atomic claims (sentence split + a `fast`-model splitter for compound sentences, behind a flag). Each claim keeps its citation numbers.
2. `src/support_agent/grounding/verify.py` — verify each claim against **only its cited chunks**:
   - Cheap exact checks first: numbers, durations, money amounts, model numbers in the claim must appear in a cited chunk.
   - Then an entailment check: a cross-encoder NLI model **or** the `fast` LLM with a strict yes/no/partial schema (pick one, configurable; say which you chose and why in `docs/GROUNDING.md`).
   - Claims with no citation that are not generic phrases (greetings, "I can connect you with an agent") are unsupported by definition.
3. Policy: unsupported claims are **removed**; if removal leaves no substantive content, or a removed claim was the main answer → handoff `low_grounding`. Store per-claim verdicts in state (traced).
4. Streaming impact: verification needs the full answer. Options: (a) stream after verification, (b) stream and retract. Choose (a) for policy/refund answers, and report the first-token latency cost. Document in `docs/GROUNDING.md`.
5. **Eval**
   - Claim-level metrics: `claim_support_rate`, `answers_with_any_unsupported_claim` (before/after), judge-flagged and human-confirmed hallucination (re-use the review workflow).
   - Measure the verifier itself on a labelled set: build `eval/sets/claims_v1.jsonl` (≥ 150 claims from real runs, human-labelled supported/unsupported via the review CSV). Report verifier precision/recall. If recall < the config target, say so.
   - Latency and cost deltas.

## Requirements
- Verification uses only the cited chunks, never re-retrieves (that would hide citation errors).
- Generic phrases whitelist is in config and small.

## Tests
- Number/amount/model exact checks on fixtures.
- Unsupported claim removed; main claim unsupported → handoff.
- Verifier never receives chunks that were not cited (assert on the fake).

## Out of scope
Rewriting unsupported claims into supported ones (possible follow-up; removal is safer and easier to evaluate).

## Done when
- [ ] Before/after hallucination numbers with CIs; verifier precision/recall on the labelled claim set; latency impact
- [ ] `make check` green; PROGRESS row 25 updated
- [ ] Interview note `docs/notes/25-claim-grounding.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(rag): claim-level grounding verification against cited sources with removal or handoff
```
