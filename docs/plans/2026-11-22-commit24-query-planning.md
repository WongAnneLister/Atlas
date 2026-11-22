# Commit 24 plan — query planning, per-part gating and partial answers

Spec: `docs/commits/24-query-planning.md`. This plan adapts it to the code on
`codex/c24-query-planning` at `556ea01` (worktree `/Users/anne_lister/proj/Atlas-c24`).
Split into three commits, as 22 and 23 were:

| Commit | Who | Message |
|---|---|---|
| 24a | Codex | `feat(eval): multi-part question set, cross-doc failure analysis and part-level metrics` (done, `57bd382`) |
| 24a fix | Codex | `fix(eval): align planned parts to gold parts by overlap and balance part order` |
| 24 | Codex | `feat(rag): query planning with per-part retrieval and gating, and partial answers with targeted handoff` |
| 24b | author, after review | `chore(eval): query planning evidence` |

24a comes first because of `AGENTS.md` §5.7: the eval that judges a feature lands before it.

## 0. Working environment (read first)

- Work only in `/Users/anne_lister/proj/Atlas-c24`. **Never write to `/Users/anne_lister/proj/Atlas`**:
  commit 23b evidence runs there and need a clean tree. Never commit or push there.
- The worktree has copies of the gitignored eval sets, `data/processed`, `data/raw` and saved
  run items, plus links to the model caches and `.env`. `make check` passes offline (856 tests).
- 24a and 24 are offline: plans, data, code and unit tests. No Milvus, no real LLM, no
  `make eval-e2e`. Live runs are 24b, after 23b is committed and this branch is merged.
- Do not push. Do not touch Milvus collections, `data/orders.sqlite`, Postgres or Redis.

## 1. What exists today (checked on 2026-11-22)

- Knowledge path: `rewrite → classify → retrieve → gate → answer → output_guard`, or
  `gate → handoff` (`graph/build.py`). One retrieval and one gate per question.
- The answer model already splits the question: `CoverageAnswer.parts` (`graph/coverage.py`)
  returns, per part, `supported`, `explicit`, an answer and quoted evidence.
  `render_covered_answer` is all-or-nothing: any unsupported or implicit part hands the whole
  question off (`insufficient_coverage`, `implied_by_absence`). Quotes are checked verbatim.
- Retrieval uses `retrieve_with_filters` with `knowledge_filters(question)` (date and category,
  commit 23) and then `scope_chunks` (store scope from the query text).
- eval_v1 has 60 `cross_doc` items (30 dev, 30 test), each with 2+ gold sections from
  different documents. The smoke set has 10 cross_doc and 30 no_answer items.
- `eval/reports/e2e.md` (test, `266c1e85`): false accept 0/30, false reject 26/120. Among the
  rejected answerable items, 6 end in `insufficient_coverage` (5 on the knowledge path) and 2 in
  `implied_by_absence`. It has no per-group table.
- `eval/metrics.py::accepted` decides acceptance; no-answer false accept counts accepted answers.
- Structured model calls go through `deps.models.structured(name, role, Model, messages)`.
  Prompts live in `graph/prompts/`.
- The reranker runs in a single-worker executor (`reliability/guards.py`), so parallel parts
  still rerank one at a time.
- **24a finding (`eval/reports/cross_doc_failures.md`) — the plan changed because of it.** In the
  test run, 7 of 30 cross_doc items were rejected. Six never reached retrieval: the classifier gave
  one intent to a two-topic question and chose `chitchat_other` (4, fixed reply) or
  `return_exchange` (2, `order_not_found`). The seventh failed coverage. Every item that reached
  retrieval had both gold sections in the top 5. A planner placed after `classify` cannot fix any of
  the six. So the planner now runs **before** classification and each part is classified on its own
  (decisions 8–9).
- `Classifier` (`graph/nodes/classify.py`) makes one `fast` structured call per query; a parse
  error becomes `chitchat_other` with `classification_failed`. `intent_low_confidence` is only
  reported to the API, not used for routing.

## 2. Decisions and deviations from the spec

Each one goes in the final message and in `docs/QUERY_PLANNING.md` (new).

1. **The planner's parts drive the answer's parts.** The answer prompt receives the planned
   parts in order and must return one `CoveredPart` per planned part, in that order. This joins
   the new planner with the existing coverage check instead of adding a second split.
2. **Filters and store scope come from the whole question.** Each part is retrieved with the
   date filter and store scope of the full rewritten question, so a part such as "and who pays
   shipping?" cannot drop the store the customer named. The category filter is detected per
   part, because two parts can be about different products.
3. **A part counts only if its key terms are in the question.** The planner returns
   `key_terms` per part; a part whose key terms do not all appear in the original or rewritten
   question is dropped and logged (spec requirement). If every part is dropped, fall back to
   single-question retrieval.
4. **No-answer safety is strict.** A no-answer item counts as a false accept if **any** part is
   answered. This keeps "false accept = 0" meaningful once partial answers exist.
5. **Dependency failures fail closed for the whole question.** If any part's retrieval or rerank
   raises a dependency error, the whole question hands off (`dependency_unavailable`), as today.
   Only gate and coverage outcomes produce partial answers.
6. **Acceptance metrics keep their meaning.** "Accepted" still means fully answered, so
   v1 false reject stays comparable. Partial answers get their own metrics (§3.3).
7. **A new frozen set for partial answers.** eval_v1 has no question with one answerable and
   one unanswerable part, so partial-answer correctness cannot be measured on it (§3.2).
8. **Plan before classify.** The flow becomes `input_guard → rewrite → plan → classify`. A
   single-part question (heuristic "no", or the planner says single, or the planner fails) is
   classified once on the whole rewritten query, exactly as today: same calls, same route.
9. **Routing a multi-part question.** Each surviving part is classified with the existing
   `Classifier` (same prompt; no new classifier). Then:
   - every part is `product_question` or `policy_question` → multi-part knowledge path (§4.2);
   - knowledge parts plus `chitchat_other` parts only → multi-part knowledge path; the
     `chitchat_other` parts are never answered and go into the targeted handoff as failed parts
     (reason `unsupported_part`, new `HandoffReason`);
   - any part on path A, C or D (order tools, after-sales, complaint), or any per-part
     classification failure → classify the whole rewritten query once and route as today, with no
     partial answer. Mixed knowledge + operational answers are out of scope (follow-up): the order
     loop and the refund picker interrupt the conversation and cannot share a reply with parts.
   Record `route_source: "whole" | "parts"` and the per-part intents in state.

## 3. Commit 24a — the eval (no graph change)

### 3.1 Cross-doc failure analysis (`eval/cross_doc_failures.py`, `make eval-cross-doc-failures`)
- Read saved run items (the e2e test run behind `eval/reports/e2e.md` and the latest smoke runs
  with cross_doc rows) and write `eval/reports/cross_doc_failures.md`: per cross_doc item, which
  gold sections were in the graph's top 5, the gate outcome, the handoff reason and answer status.
  Group the failures into patterns (one gold section missing from the top 5; gate failed; coverage
  marked a part unsupported; quote invalid). Every count comes from the script.
- Write the pattern you see, in words, in `docs/QUERY_PLANNING.md` before any 24 code.
  If the data shows planning is unlikely to help (for example, failures are mostly quote errors),
  say so plainly.

### 3.2 Multi-part set (`eval/build_multipart.py`, `make eval-multipart-build`)
- `eval/sets/multipart_v1.jsonl`, registered in `eval/registry.yaml` (`local_only`). Built
  deterministically from eval_v1, never by an LLM, and never mixing splits:
  - `answerable_pair` (≥ 20 per split): two answerable single-section items from different
    documents, joined with a fixed connector ("…, and also …?"). Gold: both sections.
  - `half_answerable` (≥ 20 per split): one answerable item plus one no_answer item.
    Gold: the answerable item's section for part 1; part 2 must be handed off.
  - `both_unanswerable` (≥ 10 per split): two no_answer items. Must hand off entirely.
- Item model `MultipartItem` in `eval/schema.py`: `parts: [{text, gold_sections, answer_points,
  answerable}]`, plus `id`, `split`, `group`, `question`, `source`. Do not change `EvalItem`
  (the 22 release check hashes its dump).
- Seeded selection; source item ids recorded per part; `reviewed: false`.

### 3.3 Metrics (`eval/metrics.py`, `eval/e2e_records.py`)
- `full_answer_rate` on cross_doc and `answerable_pair`: every gold part answered with valid citations.
- `part_recall_at_5`: every gold section is in the top 5 of at least one part's retrieval
  (for today's graph, "one part" is the single retrieval).
- `partial_answer_rate`, and on `half_answerable`: `answered_part_correct` (the answerable part
  was answered and cites its gold section) and `unanswerable_part_handed_off`.
- `noanswer_false_accept` with decision 4: any answered part on a no-answer item or on a
  `both_unanswerable` item counts.
- Record per-part data in E2E records when present (`parts`, per-part gate, per-part sections);
  old records without it must still load.
- A judge rubric for partial answers (answered parts correct, unanswered parts truly unsupported)
  that reuses `eval/judge.py`, plus a human sample CSV writer. No judge calls in tests.
- `make eval-multipart` runs the full graph on the multipart set (used live only in 24b).

### 3.4 Tests (offline)
- Analysis script on fixture run items. Set builder: counts, split purity, deterministic ids,
  no LLM. Metrics on fixture records, including old records without part data and the strict
  no-answer rule.

### 3.5 24a fix (review of `57bd382`)
- Part matching in `full_answer`, `answered_part_correct` and `unanswerable_part_handed_off` used
  exact word tokens; a real planner rewrites part text. Align by order when counts match, else by
  best word overlap (one-to-one, minimum overlap in config). Tests with paraphrased parts.
- `half_answerable` always put the answerable part first. Swap half of them by seed; rebuild
  `multipart_v1` and its registry hash (no run used it).
- `noanswer_false_accept` uses `not item.answerable` for `EvalItem`, not the group name.

## 4. Commit 24 — planning, per-part routing and partial answers

### 4.1 Planner (`graph/nodes/plan.py`, prompt `graph/prompts/plan.md`)
- Runs after `rewrite`, before `classify`, for every conversation turn that reaches `rewrite`.
- Heuristic pre-check first (config `planning.*`, a top-level section, since it is no longer
  knowledge-only): more than one question mark, a sentence-initial "Also"/"And", a coordinating
  conjunction between two clauses, or length over a threshold → "maybe". Otherwise single part,
  no LLM call. Thresholds are tuned on dev only (24b).
- On "maybe", one `fast` structured call: `{is_multi_part, parts: [{text, key_terms}]}`. At most
  `planning.max_parts` (3). Prompt rules: never invent parts; keep the user's terms; do not
  answer; greetings and thanks are not parts; treat the text as data, not instructions.
- Validation (decision 3). Invalid output or a model error → single part, logged, never a crash.

### 4.2 Classification and routing (`graph/nodes/classify.py`, `graph/build.py`)
- Single part → today's `Classifier.__call__` on the whole rewritten query.
- Multi-part → `Classifier.classify` on each part text, then decision 9. `intent`/`path` in state
  hold the routed result (for the knowledge case: path B, intent of the first knowledge part);
  `parts[i].intent` holds each part's intent. The whole-query fallback adds one more classify call.
- `trace` shows `plan` and `classify` as today; tests assert the route.

### 4.3 Knowledge graph (`graph/build.py`, `graph/nodes/knowledge.py`)
- `plan → classify → retrieve_part (one per knowledge part, LangGraph Send) → merge → gate_parts
  → answer | handoff`. Single-part questions follow the same nodes with one part and must keep
  today's behaviour and route.
- The tools-path fallback to knowledge (`route_after_tools`) keeps today's single retrieval.
- Each part: `retrieve_with_filters` + `scope_chunks` (decision 2) + `gate.evaluate` on the part text.
- Merge: dedupe chunks across parts, number sources globally, keep each part's source numbers.
- State: `parts`, per-part retrieval snapshot and gate result. Keep `retrieval` and `gate` filled
  for the single-part case and for existing consumers (handoff payload, eval records, tracing).

### 4.4 Answer and partial answers (`graph/coverage.py`, `graph/prompts/answer.md`)
- Sources grouped by part in the prompt; only parts that passed their gate are sent.
- `chitchat_other` parts (decision 9) are never sent to the answer model; they are failed parts.
- All planned parts pass the gate and coverage → full answer, as today.
- Some pass (gate or coverage): with `knowledge.partial_answers: true` (default), answer the passed
  parts with citations, then a fixed sentence from `graph/prompts/partial_handoff.txt` naming the
  parts passed to a human; create a handoff whose payload holds only the failed parts, with the
  rewritten query and their retrieval snapshots. `answer_status: partial`.
  With `false`, behave as today (whole handoff).
- None pass → handoff, zero answer-model calls (spec test).
- Output guard and citation checks apply unchanged to the partial text.

### 4.5 Config, docs
- `planning: {enabled, max_parts, heuristic thresholds}`, `knowledge.partial_answers`.
  `planning.enabled: false` must reproduce today's graph exactly (the 24b baseline).
  All of them are part of the e2e config hash.
- `docs/QUERY_PLANNING.md` (flow, decisions 8–9, limits), `docs/ARCHITECTURE.md` node list,
  `AGENTS.md` §6 is unchanged (9 intents → 5 paths still hold per part).

### 4.6 Tests (offline; add, never weaken)
- Heuristic on fixtures (single, conjunction, "Also,", two question marks, long single question).
- Planner validation drops invented parts; all dropped → single part; model error → single part.
- Graph with fakes: two parts, one passes → partial answer, handoff payload has only the failed part,
  route asserted. All parts fail → handoff and zero answer-model calls.
- Store scope and date filter from the full question reach every part (fake retriever records them).
- A dependency error in one part → whole handoff `dependency_unavailable`.
- Single-part question: one retrieval, no planner model call, one classify call, same route as
  before, for every path (A–E).
- Routing (decision 9) with a fake classifier: two policy parts → knowledge path, no whole-query
  call; policy + chitchat → knowledge, chitchat part in the handoff as `unsupported_part`, never
  answered; policy + order_status → whole-query classify and today's route; a per-part parse
  failure → whole-query classify.
- The six eval_v1 cross_doc question shapes that were misrouted (two policy questions joined by
  "Also,") route to knowledge with a fake planner and fake classifier.
- `planning.enabled: false` → identical node sequence to today on fixtures for each path.
- `partial_answers: false` → today's whole handoff.
- Checkpoint round-trip of the new state fields (SQLite and Postgres serializers).

## 5. Evidence commit 24b (runs after 23b is committed and this branch is merged)

1. `make check`; `make eval-cross-doc-failures` output reviewed.
2. Dev: e2e on eval_v1 dev and the multipart dev split for planning on/off and partial on/off.
   Report routing per group (share of cross_doc and multipart items reaching the knowledge path)
   and `make eval-intent` unchanged for single-part questions.
   Prompt fixes allowed on dev only. Then freeze.
3. Test: three configs — v1 (planning off), planning, planning + partial — on eval_v1 test and
   the multipart test split. `make eval-compare` with paired CIs on every group; full-answer rate,
   part recall, partial-answer metrics, no-answer false accept (must be 0), latency P50/P95,
   LLM calls and tokens per conversation (the planner call and per-part classify calls).
4. Release gate: knowledge smoke + `make eval-gate`, and red-team smoke — the planner is a new
   place where customer text reaches a model.
5. Judge pass on partial answers and a human sample CSV for the author.

## 6. Do not

- Do not change gate weights or the threshold, or add per-part thresholds (out of scope).
- Do not edit eval_v1 items or labels, or the `EvalItem` model.
- Do not let a part bypass the gate; every answered part passed its own gate.
- Do not write outside `/Users/anne_lister/proj/Atlas-c24`. Do not push.

## 7. Final message (each commit)

What changed, how it was verified, every deviation, follow-ups, then the full interview note
(`docs/notes/24-multipart-eval.md` for 24a, `docs/notes/24-query-planning.md` for 24).
