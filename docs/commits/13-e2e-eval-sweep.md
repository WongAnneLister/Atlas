# Commit 13 — End-to-end eval, threshold sweep, hallucination review

**Week 3 · depends on: 11, 12** · this is the Week 3 checkpoint (**no-answer false-accept = 0%**)

## Context
Now we measure the whole system and choose the gate threshold with data.
Rule from the PRD: sweep 0.05 → 0.95, plot false-accept and false-reject, and pick the **lowest threshold with 0 false-accepts on dev**.
Then report everything on **test**. Do not reuse any threshold from other projects.

## Read first
- `docs/PRD.md` → Evaluation and Success criteria
- `AGENTS.md` §5.1
- `eval/reports/gate_signals_dev.md` (from 11), `eval/metrics.py`

## Definitions (put these in `eval/metrics.py` docstrings and in `docs/RESULTS.md`)
- **Accepted** = the system gave a substantive answer: knowledge `answer` node, tools-path final answer, or refund decision reply.
- **Not accepted** = handoff (any reason) or a path-E template reply.
- **False-accept** = a `no_answer` item that was accepted. **False-reject** = an answerable item that was not accepted.
- In the sweep (gate only) these are computed from the gate decision; in e2e they are computed from the final outcome, so a misrouted no_answer question that the tools path answers still counts as a false-accept.

## Task
1. `eval/sweep.py` + `make sweep`:
   - On **dev**: compute the gate score once per question (cache it), then for thresholds 0.05..0.95 step 0.01: false-accept rate (no_answer items that pass), false-reject rate (answerable items that fail), pass rate.
   - Choose `t* = min t such that false-accept(dev) = 0`. Also report the margin: the highest no_answer score on dev and the gap to `t*`.
   - Write `eval/reports/threshold_sweep.md` + `threshold_sweep.png` (two curves, vertical line at `t*`), and the table of the 10 no_answer items with the highest scores (to see how close they came).
   - Write `t*` into `configs/default.yaml` → `gate.threshold` **with a comment** pointing at the report and the git SHA. This is the only way the threshold gets set.
   - Then evaluate `t*` once on **test** and report false-accept / false-reject there. If test false-accept > 0, report it honestly, list the items, and do **not** change the threshold using test. Write next steps in PROGRESS.
2. `eval/e2e_eval.py` + `make eval-e2e` — runs the full graph (real models) on `--split` (default `test`), one fresh thread per question, customer id from config:
   - Per item record: intent, path, trace, gate result, answer, citations, handoff reason, latency to first token and full answer, token usage (from model response metadata).
   - Metrics: false-accept (no_answer), false-reject (answerable), Recall@5 inside the graph, citation validity (cited sections ∩ gold), latency P50/P95, tokens and cost per intent (price table in config; mark as estimate).
   - Writes `eval/reports/e2e.md` + `e2e_<split>.jsonl`.
3. `eval/judge.py` + `make eval-judge` — hallucination check:
   - An LLM judge (prompt `eval/prompts/judge.md`) gets the answer + the cited source texts and lists any claim not supported by them → `flagged` with the claims.
   - Writes `eval/sets/hallucination_review.csv` for a **human** to confirm each flagged item (`confirmed` column). `make eval-judge-import` reads it back.
   - Report both: judge-flagged rate and human-confirmed rate. Until a human fills the CSV, the confirmed rate is shown as "pending".
4. `eval/compare.py` + `make eval-compare A=<report.jsonl> B=<report.jsonl>` — diff two runs: metric deltas and questions whose outcome changed. Used for every later change.
5. Update `docs/RESULTS.md` (create it): one table per experiment, every number with its report path. Include a short "what we learned" for the threshold (e.g. the trade-off between false-accept and false-reject at `t*`).

## Requirements
- The sweep uses cached gate scores, so it costs no LLM calls.
- `make eval-e2e` is resumable (skip items already in the output file for the same config hash).
- Every report has the standard header (git SHA, config hash, models, eval file hash, split, date).

## Tests
- Sweep picks the right `t*` on a hand-made score list; handles "no threshold reaches 0" (report it, set nothing).
- Rate calculations on fixtures.
- Compare tool on two small fixture runs.

## Out of scope
Per-intent thresholds, partial answers, query decomposition (P1 — log them in PROGRESS follow-ups if the failure analysis points there).

## Done when
- [ ] `gate.threshold` set from the dev sweep, with comment
- [ ] `eval/reports/e2e.md` on test exists; `docs/RESULTS.md` filled
- [ ] Hallucination review CSV exported (human step pending is OK)
- [ ] `make check` green; PROGRESS row 13 updated with t*, test false-accept, test false-reject, P95 latency
- [ ] **Checkpoint 3**: if test false-accept = 0%, mark "Week 3 gate passed" in PROGRESS; otherwise mark "NOT passed" and why
- [ ] Interview note `docs/notes/13-e2e-eval-sweep.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(eval): end-to-end evaluation, dev-split threshold sweep and LLM-judge hallucination review
```
