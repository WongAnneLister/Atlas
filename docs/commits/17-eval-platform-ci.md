# Commit 17 — Eval platform: versioned datasets, confidence intervals, judge calibration, CI release gate

**Phase 2 · depends on: 16 (Checkpoint 4 passed)**

## Context
Phase 2 changes the system many times. Each change must be judged the same way, with uncertainty shown, and a bad change must
be blocked automatically. On 60 no-answer items, "0 false-accepts" has a wide confidence interval; on 240 answerable items a
1–2 point change can be noise. This commit turns the v1 eval scripts into a small eval platform. Every later commit depends on it.

## Read first
- `AGENTS.md` §5.1, §5.7
- All of `eval/`, `docs/RESULTS.md`, `.github/workflows/ci.yml`

## Task
1. **Dataset registry** — `eval/registry.yaml`: every eval set (`eval_v1`, `intent`, later `redteam`, `scenarios`, …) with version, file hash, item count, split sizes, `reviewed` count, changelog line.
   `make eval-validate-all` checks hashes match the registry (a changed file without a version bump fails).
2. **Run records** — one format for all eval outputs: `eval/runs/<run_id>/` with `manifest.json` (git SHA, config hash, models, dataset versions, split, seed, start/end time, cost) + `items.jsonl` + `metrics.json`. Refactor existing scripts to write it. Keep the old report files generated from run records.
3. **Statistics** — `eval/stats.py`:
   - Bootstrap 95% CI for every rate/mean metric (fixed seed, 2000 resamples).
   - For 0/n results also report the Wilson / rule-of-three upper bound (e.g. "0/30 → upper bound ≈ 10%"), so we never claim "0% risk".
   - Paired comparison for two runs on the same items: paired bootstrap of the difference, plus McNemar's test for binary outcomes.
   - `make eval-compare` shows delta, CI of the delta, and a verdict: `better | worse | no significant change`.
4. **Judge calibration** — `eval/judge_calibration.py`: using the human-confirmed rows from the hallucination review (commit 13), compute judge precision/recall vs human and Cohen's kappa. Write `eval/reports/judge_calibration.md`. Every report that uses a judge metric shows the judge's kappa next to it. If fewer than 30 human labels exist, say so and print how many more are needed.
5. **CI release gate** — `.github/workflows/eval-gate.yml`:
   - Trigger: nightly + manual + on PRs with label `run-evals` (needs LLM secrets; skip cleanly if absent).
   - Runs a **fixed smoke subset** (`eval/sets/smoke.jsonl`: all 30 test no-answer items + 40 stratified answerable + later red-team items) and compares to the stored baseline run on `main`.
   - Gate rules in `eval/gate_rules.yaml`: false-accept must be 0; other metrics must not be `worse` per the paired test. Posts a markdown summary to the PR (or job summary).
   - `make eval-baseline` promotes a run to baseline (writes `eval/baselines/main.json`). Only from `main`.
6. `docs/EVAL_PLATFORM.md` — how to add an eval set, how CIs are computed, the gate rules, and how to read a compare report.

## Requirements
- Existing `make` targets keep working (now backed by run records).
- Stats code is pure and fully unit-tested; no LLM calls in tests.
- The smoke subset is drawn from **test** with a fixed seed and never used for tuning.

## Tests
- Bootstrap CI on a known distribution (coverage roughly right with a fixed seed).
- Rule-of-three bound for 0/30 and 0/60.
- McNemar on a hand-made 2×2 table.
- Gate rules: a fixture run with one false-accept fails; a fixture run with a significant drop fails; noise-level change passes.
- Registry hash mismatch fails validation.

## Out of scope
Online eval (32), multi-turn simulation (27), red-team set (20).

## Done when
- [ ] All v1 reports regenerated from run records, numbers identical to before (prove it with `eval-compare` → no change)
- [ ] `docs/RESULTS.md` tables now show 95% CIs and upper bounds for 0/n results
- [ ] Eval gate workflow runs (or skips cleanly without secrets) on a test PR
- [ ] `make check` green; PROGRESS updated (add rows for phase 2 if missing)
- [ ] Interview note `docs/notes/17-eval-platform-ci.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(eval): versioned eval registry, run records, bootstrap CIs, judge calibration and CI release gate
```
