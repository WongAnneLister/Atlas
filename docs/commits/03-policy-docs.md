# Commit 03 — Build policy documents and product catalog

**Week 1 · depends on: 02**

## Context
One-question-one-answer FAQs make retrieval too easy and the metrics meaningless. The PRD asks us to merge related FAQs into
a few **long policy documents** (Returns, Shipping, Payments, Membership, plus others the data justifies) so chunking and
cross-document retrieval are really tested. Product info becomes a **product catalog** used for model-number questions.

## Read first
- `docs/DATA_NOTES.md`, `docs/LICENSES.md` (from commit 02)
- `AGENTS.md` §5.1 and §5.3

## Task
1. `src/support_agent/data/build_docs.py` + `make data-docs`:
   - Load FAQs from both FAQ datasets. Normalise text (strip HTML, fix whitespace, drop exact and near duplicates — e.g. normalised-text hash, then a simple similarity check). Log how many were dropped and why.
   - Assign each FAQ to a **topic** (returns, refunds, shipping, payments, membership/account, orders, warranty, other). Use keyword rules first; use the `fast` LLM only for leftovers, and cache its decisions to `data/processed/topic_cache.jsonl` so reruns are deterministic and free.
   - For each topic write one Markdown doc `data/processed/docs/<topic>.md`:
     - YAML front matter: `doc_id`, `title`, `source_datasets`, `built_at`.
     - Sections `## <heading>` with a stable **section id** in an HTML comment, e.g. `<!-- section: returns.window -->`. One section per sub-topic; merge FAQs that say the same thing into normal prose. Keep every fact from the source; do not invent new policy facts.
     - If the LLM is used to rewrite Q&A into prose, keep a mapping `section_id -> [source faq ids]` in `data/processed/docs/provenance.json`.
   - Products: write `data/processed/catalog/products.jsonl` (one product per line: `product_id`, `model`, `name`, `attributes`, `description`, `source_id`) **and** render them into `data/processed/docs/catalog_<category>.md` with one section per product (`<!-- section: product.<model> -->`).
     Make sure similar model numbers (e.g. W40 / W40 Pro / W400) are kept as separate sections — the eval needs them.
2. `src/support_agent/data/validate_docs.py` (run at the end of `make data-docs`):
   - Every section has a unique id; no empty sections; every source FAQ is covered by some section (report coverage %).
   - Prints a summary table: docs, sections, words per doc, coverage.
3. Write `docs/DOCS_BUILD.md`: topic rules, dedupe rules, numbers from the validator, known limitations.
4. Whether `data/processed/` is committed follows `docs/LICENSES.md`. If unclear, gitignore it.

## Requirements
- Deterministic: same input + same cache → byte-identical output.
- No new facts. The LLM may only rephrase and merge; add a check that numbers (days, amounts, percentages) in a section all appear in its source FAQs.

## Tests
- Dedupe on a small fixture.
- Topic rules on fixture questions.
- Section id uniqueness + numbers-preserved check on a fixture doc (use a fake LLM).

## Out of scope
Chunking (06), eval questions (05).

## Done when
- [ ] `make data-docs` produces the docs and the validator passes with ≥ 98% FAQ coverage (or the real number and why)
- [ ] At least 4 long policy docs and a product catalog exist
- [ ] `make check` green; PROGRESS row 03 updated (docs, sections, coverage)
- [ ] Interview note `docs/notes/03-policy-docs.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(data): merge FAQs into long policy docs with stable section ids and build product catalog
```
