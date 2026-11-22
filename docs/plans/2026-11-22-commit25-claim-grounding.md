# Commit 25 plan — claim-level grounding after generation

Spec: `docs/commits/25-claim-grounding.md`. This plan adapts it to the code on
`codex/c25-claim-grounding` at `b864da2` (worktree `/Users/anne_lister/proj/Atlas-c25`).
Split into three commits, as 22–24 were:

| Commit | Who | Message |
|---|---|---|
| 25a | Codex | `feat(eval): claim extraction, claim set builder and claim-level metrics` |
| 25 | Codex | `feat(rag): claim-level grounding verification against cited sources with removal or handoff` |
| 25b | author + Claude, after 24b | `chore(eval): claim grounding evidence` |

25a comes first because of `AGENTS.md` §5.7: the eval that judges a feature lands before it.

## 0. Working environment (read first)

- Work only in `/Users/anne_lister/proj/Atlas-c25`. **Never write to `/Users/anne_lister/proj/Atlas`**:
  commit 24b evidence runs there and need a clean tree. Never commit or push there.
- The worktree has copies of the gitignored eval sets, `data/processed`, `data/raw` and saved
  run items, plus links to the model caches and `.env`. `make check` passes offline.
- 25a and 25 are offline: no Milvus, no real LLM, no `make eval-e2e`. Live runs are 25b.
- Do not push. Do not touch Milvus collections, `data/orders.sqlite`, Postgres or Redis.
- Another session is changing `eval/e2e_eval.py` and `eval/multipart_eval.py` (rerank cache and
  `--workers`). Keep edits to those two files small and local, to make the later merge easy.

## 1. What exists today (checked on 2026-11-22)

- Knowledge answers come from `CoverageAnswer` (`graph/coverage.py`): per part, a model-written
  `answer` plus verbatim `evidence` quotes that code checks against the numbered sources.
  `render_covered_part` appends the part's citation numbers to the paragraph. So every citation
  belongs to a whole paragraph, not to a sentence, and the answer text itself is never checked:
  only the quotes are. A sentence the quotes do not support can still reach the customer.
- Multi-part answers (commit 24) render one paragraph per answered part (`_render_parts`),
  then add the fixed partial-handoff sentence. The single-question path renders the same way.
- Fixed text added by code: the historical-policy notice (`policy_version_notice.txt`), the
  partial-handoff sentence (`partial_handoff.txt`), handoff messages. None of it is model-written.
- Order-tool answers already have sentence-level grounding (`graph/order_grounding.py`): code
  splits sentences, the model must quote tool data per sentence, code checks the quotes. The
  output guard has `unbacked_commitment` (`guardrails/output.py`). Reuse their sentence splitter
  and patterns instead of writing new ones.
- Refund replies: `check_decision` (`graph/refund_decision.py`) already requires a valid citation
  per reason and checks the return window in code. Reasons mix order facts and policy.
- The API builds token events from the finished answer after `output_guard`
  (`api/events.py`), so answers are already streamed after all checks. Confirm this in code.
- Judge: `eval/judge.py`, `eval/reports/hallucination_review.md` (test run of 2026-11-10: judge
  flagged 8/150; **0 human confirmations**), `eval/reports/judge_calibration.md` (0/30 labels).
- Every saved E2E run with answer text is on the **test** split (`eval/runs/e2e-test-*`,
  `smoke-test-*`). Dev answers will exist only after 24b (`eval_v1` dev, two configs).

## 2. Decisions and deviations from the spec

Each one goes in the final message and in `docs/GROUNDING.md` (new).

1. **Scope: knowledge answers only** (single-question and multi-part). Refund replies are out
   of scope: their reasons mix order facts with policy, `check_decision` already checks them,
   and a policy-only verifier would remove true order facts. Follow-up.
2. **Verify only model-written text.** Templates added by code (notice, partial-handoff
   sentence, handoff messages) are never claims. The whitelist in config covers only short
   generic phrases the model writes ("You can contact support for help."); keep it under 10.
3. **A claim's sources are its paragraph's cited chunks.** Citations are per paragraph, so each
   sentence in a part is checked against the chunks that part cites, and nothing else
   (spec: never re-retrieve).
4. **Verifier: the `fast` LLM with a quote requirement, not an NLI model.** One structured call
   per answer; code numbers every claim so none is skipped. For each claim the model returns
   `supported | partial | unsupported` and, when supported, a short verbatim quote from that
   claim's sources; code checks the quote. `partial` counts as unsupported. Reasons: no new
   model weights or dependency, the same quote-check pattern as coverage and order grounding,
   and the NLI option would need a separate download and calibration. Exact checks run first.
5. **Exact checks first, in code:** every number, duration, money amount, percentage and
   model number in a claim must appear in its cited chunks (normalised: "30 days" = "30-day").
   An exact-check failure is unsupported without a model call.
6. **Removal policy per part.** Unsupported claims are removed. A part fails with reason
   `low_grounding` if its first claim (the main answer) is removed or no substantive claim is
   left. Failed parts follow commit 24: with `knowledge.partial_answers` on, the other parts are
   still answered and the failed part is handed off; if no part is left, the whole question
   hands off with new `HandoffReason.LOW_GROUNDING`. A single-question answer is one part.
7. **Fail closed.** If the verifier call fails or returns invalid output, the answer is not
   released: hand off (`dependency_unavailable` for dependency errors, else `low_grounding`).
8. **Switch.** `grounding.enabled` (default true). `false` must reproduce today's graph exactly;
   it is the 25b baseline. All grounding settings are in the e2e config hash.
9. **Compound splitter behind a flag, default off.** Sentence split by code first; the `fast`
   splitter for compound sentences is `grounding.split_compound` and is evaluated in 25b on dev.
10. **Labels are human.** The claim set needs the author's labels. Code drafts nothing into the
    label column and the labelling CSV does not show the verifier's or judge's verdict (blind).
11. **Synthetic negatives, reported separately.** Real answers are mostly supported (judge
    flagged 8/150), so recall on real claims alone would rest on a handful of cases. 25a adds a
    second, clearly separate group of perturbed claims built by code (number, duration or amount
    changed; model number swapped; a sentence from an uncited chunk of another document). Their
    label is known by construction. Precision/recall are reported per group, never pooled.

## 3. Commit 25a — the eval (no graph change)

### 3.1 Claim extraction (`eval/claims.py`)
- From a saved E2E record (`E2ERecord`, single or multi-part): the model-written part answers,
  split into claims with the same splitter the feature will use (put the splitter in
  `src/support_agent/grounding/split.py` now, reusing `order_grounding.py` logic; 25 imports it).
  Each claim keeps its record id, split, part index, sentence index and the cited chunk texts.
- Templates are removed before splitting (decision 2). Records without an accepted or partial
  answer have no claims.

### 3.2 Claim set (`eval/build_claims.py`, `make eval-claims-build`)
- `eval/sets/claims_v1.jsonl`, registered in `eval/registry.yaml` (`local_only`), model
  `ClaimItem` in `eval/schema.py`: `id, split, group (real | synthetic), source_run, source_item,
  part, claim, sources[{n, section_id, text}], label (supported | unsupported | null),
  label_source (human | construction), perturbation (null or kind), reviewed`.
- Real group: at least 150 claims per split once labelled is the target for test; dev needs at
  least 80. Seeded sampling across items so one long answer cannot dominate (at most 3 claims
  per item). Input runs are passed on the command line; the builder records their paths and
  hashes. Do not change `EvalItem`.
- Synthetic group: at least 60 per split, from real supported-looking claims, perturbed by code
  (decision 11), seeded. A perturbation that leaves the claim text unchanged is dropped.
- Splits never mix: dev claims come from dev runs, test claims from test runs.
- `make eval-claims-label` writes the blind labelling CSV for the author
  (`eval/sets/claims_v1_labels.csv`, local): claim, its sources, empty `label` and `note`
  columns. `--import` reads the filled CSV back into `claims_v1.jsonl` and bumps the registry
  entry through the existing registry tooling. The importer refuses unknown ids, empty labels
  and edits to claim text.

### 3.3 Metrics (`eval/metrics.py`, `eval/e2e_records.py`)
- Record per-claim verdicts in E2E records when present (`claims: [{part, text, verdict,
  reason, removed}]`); old records without them must still load.
- Per run: `claim_support_rate` (verifier-supported claims / all claims, from records),
  `answers_with_any_unsupported_claim`, `claims_removed_per_answer`, `low_grounding_handoff_rate`.
  Before/after hallucination uses the judge on final answers plus human confirmation on a sample
  (reuse `eval/judge.py` and the review workflow; no judge calls in tests).
- Verifier on the claim set (`eval/claims_eval.py`, `make eval-claims`, used live in 25b):
  precision, recall and F1 for the `unsupported` class, per split and per group, with Wilson
  intervals; a `grounding.target_recall` in config that the report compares against.
- Acceptance does not change meaning: an answer with removed claims is still "accepted" if it
  was released; removal is reported by the new metrics.

### 3.4 Tests (offline)
- Splitter on fixtures (abbreviations, lists, decimals, model numbers, citation markers).
- Extraction drops templates; multi-part records keep part indices; old records load.
- Builder: split purity, seeded determinism, per-item cap, perturbations change the text and
  keep the sources.
- Label import: rejects unknown ids, empty labels, changed claim text.
- Metrics on fixture records.

## 4. Commit 25 — verification and removal

### 4.1 Claims and checks (`src/support_agent/grounding/`)
- `split.py` (from 25a), `claims.py` (claims with their part's cited chunk numbers; optional
  compound splitter, decision 9), `exact.py` (decision 5), `verify.py` (decision 4, one call,
  prompt `graph/prompts/verify_claims.md`, schema with one verdict per numbered claim; code
  rejects a reply that skips or adds claim numbers).
- The verifier receives each claim, its question as context, and the cited chunks of its part.
  Use the planned part question for multipart answers or the original item question otherwise.
  Only the cited chunks count as evidence. Use the same `grounding.generic_phrases` list as
  extraction to skip generic phrases.

### 4.2 Graph (`graph/nodes/knowledge.py`, `graph/build.py`)
- A `ground` step after rendering and before `output_guard`, on the knowledge path only, for
  both `answer` (single question) and `_render_parts` (multi-part). Implement it where the
  route stays readable; graph tests assert the node sequence.
- Apply decision 6. Rebuild citations from the remaining text with `_check_citations`, so
  citation records match what is shown. Store per-claim verdicts in state and in the trace.
- `answer_status` gains `grounding_removed` only if a value is needed for reporting; prefer a
  separate state field `claims_removed` and keep `answered`/`partial` meanings unchanged.

### 4.3 Config and docs
- `grounding: {enabled, split_compound, generic_phrases, target_recall, verifier_role}`,
  `reliability.timeouts_s.verify`. Model names come from roles only.
- `docs/GROUNDING.md`: flow, decisions 1–11, streaming (answers already stream after checks;
  the cost is first-token latency, measured in 25b), limits.

### 4.4 Tests (offline; add, never weaken)
- Exact checks on fixtures: numbers, durations, money, percentages, model numbers.
- Unsupported non-main claim removed and citations rebuilt; main claim unsupported → part fails;
  single question → handoff `low_grounding` with zero further model calls.
- Multi-part: one part loses its main claim → partial answer with that part handed off.
- Verifier never receives chunks that were not cited by the claim's part (assert on the fake).
- Verifier reply that skips a claim → treated as invalid → handoff.
- Verifier dependency error → handoff `dependency_unavailable`.
- Templates are never sent to the verifier.
- `grounding.enabled: false` → identical node sequence and answer to today on fixtures.
- Checkpoint round-trip of the new state fields (SQLite and Postgres serializers).

## 5. Evidence commit 25b (after 24b is committed and this branch is merged)

1. Build `claims_v1` from the 24b dev runs (dev) and the 24b test runs (test). **The author
   labels the real claims** with `make eval-claims-label` (about 150 test + 80 dev claims; plan
   on roughly an hour). Also label the 30 judge-calibration rows that are still missing.
2. Dev: tune the verifier prompt and `split_compound` on dev claims only, then freeze.
3. Test: verifier precision/recall per group with intervals, against `target_recall`.
4. E2E on eval_v1 test and the multipart test split, `grounding.enabled` false vs true, paired
   (`make eval-compare`): claim metrics, judge-flagged answers with a human-confirmed sample,
   false reject and no-answer false accept (must stay 0), first-token and full latency, cost.
5. Red-team smoke: the verifier is a new place where answer text and source text reach a model.

## 6. Do not

- Do not change gate weights or the threshold, or the coverage prompt `answer.md`.
- Do not edit eval_v1 items or labels, or the `EvalItem` model.
- Do not fill label columns by code or by a model; labels are the author's.
- Do not let the verifier see uncited chunks or re-retrieve.
- Do not write outside `/Users/anne_lister/proj/Atlas-c25`. Do not push.

## 7. Final message (each commit)

What changed, how it was verified, every deviation, follow-ups, then the full interview note
(`docs/notes/25-claim-eval.md` for 25a, `docs/notes/25-claim-grounding.md` for 25).
