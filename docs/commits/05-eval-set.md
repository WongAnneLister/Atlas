# Commit 05 — 300-question eval set (before any retrieval code)

**Week 2 · depends on: 03**

## Context
The PRD rule: **build the eval set first, then the retrieval code.** Every later change is judged by this set.
300 questions = 5 groups × 60: `basic_policy`, `model_number`, `colloquial`, `cross_doc`, `no_answer`.
Each group is split 30 `dev` / 30 `test`. Tuning happens on dev only; results are reported on test.

## Read first
- `docs/PRD.md` → Evaluation
- `AGENTS.md` §5.1 (honesty rules) and §6 (eval record schema)
- `data/processed/docs/*.md` and `products.jsonl` (to see the real section ids)

## Task
1. `eval/schema.py` — Pydantic `EvalItem`:
   `id, group, split, question, gold_sections: list[str], answer_points: list[str], answerable: bool, source: str, reviewed: bool = False, notes: str = ""`.
   Rules: `no_answer` ⇒ `answerable=False` and empty `gold_sections`; `cross_doc` ⇒ ≥ 2 gold sections from ≥ 2 different docs.
2. `eval/build_set.py` + `make eval-build` — drafts candidates per group, then samples 60:
   - **basic_policy**: questions from the source FAQs; gold = the section that FAQ landed in (`provenance.json`).
   - **model_number**: pick products that have look-alike models; ask about an attribute that **differs** between them. Gold = that product's section.
   - **colloquial**: take basic-policy-style questions and rewrite them using real Bitext phrasings for the matching intent (slang, typos, no punctuation). Keep the same gold.
   - **cross_doc**: LLM drafts questions that need 2–3 sections from different docs (pairs chosen by code, e.g. returns × payments-coupons). Answer points come from both sections.
   - **no_answer**: LLM drafts plausible e-commerce questions on topics absent from the docs (payment methods we don't list, store locations, unrelated products…). **Then filter**: drop any candidate whose key terms appear in the corpus (BM25 over raw docs is fine here) — those may be answerable.
   - Drafts go to `eval/sets/candidates.jsonl`; the sampled 300 go to `eval/sets/eval_v1.jsonl` with `reviewed=false`. Use a fixed seed. Stratified dev/test split.
3. `eval/validate_set.py` + `make eval-validate`:
   - Schema valid, 60 per group, 30/30 split, ids unique, no duplicate questions (normalised).
   - Every gold section id exists in the current docs.
   - Every answer point is supported by its gold section text (exact numbers must appear; for phrases use token overlap ≥ a config threshold). Print failures.
   - No test-split question is a near-duplicate of a dev-split one.
4. `eval/review.py` + `make eval-review` — exports `eval/sets/review.csv` (question, gold section text, answer points, a blank `ok` column) and imports it back, setting `reviewed=true` only for rows marked `ok`. **You (the agent) must not mark anything reviewed** — a human does.
5. `docs/EVAL_SET.md` — how each group was built, the validator rules, and the review status count.

## Requirements
- The LLM is only a drafter. Code decides gold labels from provenance where possible.
- Every item keeps `source` (e.g. `faq:maktek:123`, `gen:cross_doc:v1`).
- The eval file is committed only if `docs/LICENSES.md` allows; otherwise commit the build script + seed and gitignore the file.

## Tests
- Schema rules (no_answer / cross_doc constraints).
- Validator catches: missing section, unsupported number, dev/test leak — each on a tiny fixture.
- Review import only flips rows marked `ok`.

## Out of scope
Any retrieval or metric code (08, 13).

## Done when
- [ ] `eval_v1.jsonl` has 300 items, validator passes (or failures are listed in PROGRESS)
- [ ] `review.csv` exported for the human
- [ ] `make check` green; PROGRESS row 05 updated with "reviewed: 0/300 — waiting for human review"
- [ ] Interview note `docs/notes/05-eval-set.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(eval): build 300-question eval set with dev/test split, validator and review workflow
```
