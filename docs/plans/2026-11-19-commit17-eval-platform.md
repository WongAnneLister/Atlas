# Commit 17 execution plan — eval platform and CI release gate

Read this together with `docs/commits/17-eval-platform-ci.md` (the task) and `AGENTS.md` (the rules).
This plan does not change the task. It fixes the places where the task prompt does not match the
repository as of 2026-11-19, and it orders the work. If this plan and `AGENTS.md` disagree, follow `AGENTS.md`.

## 0. Preconditions (check first; stop and report if one fails)

1. **Checkpoint 4.** `AGENTS.md` §8 forbids starting phase 2 before Checkpoint 4 is marked in
   `docs/PROGRESS.md`. The author recorded an explicit waiver on 2026-11-19 (the "Checkpoint 4 waiver" line
   under Checkpoints). Checkpoint 4 itself is still not passed; do not mark it and do not describe v1 as shipped.
2. **Branch.** `main` contains commits 15, 16 and 16a–16c (`git log main..codex/holdout-gate-round3` is empty).
   Work on branch `codex/c17-eval-platform`, which is `main` plus one commit with the waiver.
   Make the commit-17 commit on top of it.
3. `make check` is green before you change anything.

## 1. Facts about the repository that change the task

| Task prompt says | Reality | What to do instead |
|---|---|---|
| Commit `eval/sets/smoke.jsonl` | `eval/sets/*.jsonl` is gitignored: eval text inherits unclear licenses (`docs/LICENSES.md`) | Commit only IDs: `eval/smoke.yaml` (seed, rule, source set version + hash, item IDs). `make eval-smoke-build` writes the local, ignored `eval/sets/smoke.jsonl` from it. |
| `eval/runs/<run_id>/items.jsonl` | Items embed question and answer text | Commit `manifest.json` and `metrics.json`; gitignore `eval/runs/*/items.jsonl`. |
| Baseline in `eval/baselines/main.json` | Must not contain question text either | Store run id, manifest, metrics, and per-item outcomes keyed by ID (booleans, handoff reason, group). No text. |
| CI runs the smoke subset | GitHub-hosted runners have no corpus, no Milvus (it is on a VPS behind SSH), no reranker cache | The workflow always runs its preflight; it runs evals only on a runner that has data and secrets. On a hosted runner it skips cleanly with a job summary. The gate *logic* is tested offline in `make check`. |
| `make eval-baseline` only from `main` | This commit is built on a feature branch | Ship the mechanism without a baseline file. The human promotes the first baseline on `main` after merge (see §5). |
| "Refactor existing scripts" | `eval/` has ~55 scripts, most are one-off experiment reports (13c–16b) | Move only the v1 core onto run records: `e2e_eval`, `sweep`, `retrieval_eval`, `intent_eval`, `judge`. List the rest as "legacy reports" in `docs/EVAL_PLATFORM.md`. |
| Judge calibration from human-confirmed rows | `eval/reports/hallucination_review.md`: 0/150 human confirmations | Build the tool and its tests; the report states 0 labels and how many are needed. Never create labels. |
| numpy/scipy for stats | Neither is a direct dependency | Add `numpy` only. Do McNemar with an exact binomial test via `math.comb`; Wilson by formula. No scipy, so no stub problems for mypy. |
| `make eval-compare A B` | Already exists (`eval/compare.py`, e2e JSONL only) | Extend it: accept a run dir or a legacy JSONL; keep the old CLI working. |

## 2. Design (fixed here so the work does not drift)

### 2.1 Statistics — `eval/stats.py` (pure, numpy only, < 300 lines)
- `bootstrap_ci(values, stat="mean", n_resamples, seed, alpha) -> Interval(point, low, high)`; percentile method.
  Defaults come from config: add `eval.stats: {n_resamples: 2000, seed: <int>, alpha: 0.05}` to `configs/default.yaml`.
- `wilson_interval(k, n, alpha)` and `rule_of_three_upper(n) = 3 / n`.
  For k = 0 every report prints both, e.g. `0/30 (95% upper bound: 10.0% rule of three, 11.4% Wilson)`.
- `paired_bootstrap_diff(a, b, ...)`: resample item indices jointly; returns delta and its CI.
- `mcnemar_exact(b, c) -> p_value`: two-sided exact binomial on discordant pairs.
- `cohens_kappa(table_2x2)`.
- `verdict(metric, ...) -> "better" | "worse" | "no significant change"`.
  Binary metrics: significant when McNemar p < alpha; direction from the sign of the delta and the metric's direction.
  Continuous metrics: significant when the paired-bootstrap CI of the delta excludes 0.
  Metric directions (lower/higher is better) live in `eval/gate_rules.yaml`, not in code.

### 2.2 Dataset registry — `eval/registry.yaml` + `eval/registry.py`
- One entry per set in `eval/sets/`: `eval_v1`, `intent_holdout`, `intent_extra`, `holdout_near_miss_v1`,
  `holdout_near_miss_v2`, `store_controls_v1`, `paraphrase_holdout_v1`, `smoke`. Inspect the real files first;
  do not register review CSVs or caches.
- Fields: `name, version, path, sha256, items, splits {dev, test, …}, reviewed, license_scope: local_only, changelog: [ … ]`.
- `make eval-validate-all`: file present and hash differs → fail with "bump the version and add a changelog line".
  File absent → `SKIP (local only)`, exit 0. `--require-present` turns absence into a failure (used by the eval workflow).
- `python -m eval.registry bump NAME --version vN --note "…"` refuses when the version does not change.

### 2.3 Run records — `eval/run_record.py`
- `eval/runs/<run_id>/manifest.json`: git SHA, dirty flag, config hash, models, dataset name → registry version + hash,
  split, seed, start/end time (UTC), cost (null + "price not set" while `costs.prices` is empty), command line, kind.
- `items.jsonl` (gitignored) and `metrics.json` (committed; numbers + CIs only).
- `run_id = <kind>-<split>-<YYYYMMDD>-<shortsha>[-<suffix>]`; refuse to overwrite an existing dir.
- Pydantic models for all three files. Report renderers read run records only.

### 2.4 Legacy import (proof that numbers did not move)
- `eval/import_legacy.py` wraps an existing local JSONL/CSV into a run dir without re-running anything:
  at least `eval/runs/e2e-test-c15.jsonl` (current `eval/reports/e2e.md`), `eval/runs/baseline-001-e2e-test.jsonl`
  (`e2e-001`), the sweep gate-score files, and `eval/reports/retrieval_{dev,test}.csv`.
- Regenerate each v1 report from the imported run. Then:
  `make eval-compare A=<legacy file> B=eval/runs/<imported id>` must show delta 0 and `no significant change` on every metric,
  and `git diff eval/reports/` may only add CI/upper-bound text, never change an existing number.
- If a v1 report has no per-item file locally, say so in PROGRESS; do not re-run models to recreate it.

### 2.5 Judge calibration — `eval/judge_calibration.py`
- Sample for human labelling: every judge-flagged row plus a seeded random sample of unflagged rows
  (recall needs both). Export `eval/sets/judge_calibration.csv` (gitignored) with an empty `human_label` column.
- With ≥ 30 labels: precision, recall, Cohen's kappa, each with a CI. With fewer: print the count and how many more are needed.
- Write `eval/reports/judge_calibration.md`. Every report that shows a judge metric
  (`hallucination_review.md`, `e2e.md`, RESULTS, README block) prints the kappa next to it, or `kappa: n/a (0/30 labels)`.

### 2.6 Smoke set and release gate
- `make eval-smoke-build`: from `eval_v1` **test** split only, fixed seed from config: all 30 `no_answer` items +
  40 answerable stratified 10 per group (`basic_policy`, `model_number`, `colloquial`, `cross_doc`). Writes `eval/smoke.yaml`
  (IDs) and the local JSONL; registers `smoke` in the registry. Leave a `redteam: []` slot for commit 20.
- `make eval-smoke`: runs the full graph on the smoke set and writes a run record.
- `eval/gate_rules.yaml`: hard rule `no_answer false_accept count == 0`; per-metric direction and test for
  `false_reject`, `pass_rate`, graph `recall@5`, citation validity, latency P95; a `redteam` placeholder.
- `eval/gate.py` (pure): `evaluate(run, baseline, rules) -> GateResult` + markdown. `make eval-gate RUN=eval/runs/<id>`.
  Exit 1 on any hard-rule breach or any `worse` verdict; exit 2 with "no baseline" when `eval/baselines/main.json` is missing.
- `make eval-baseline RUN=…`: refuse unless the current branch is `main`, the tree is clean, and the run's SHA is `HEAD`.
- `.github/workflows/eval-gate.yml`: triggers `schedule` (nightly), `workflow_dispatch`, and `pull_request`
  (`labeled`, `synchronize`) filtered to label `run-evals`. `runs-on: ${{ vars.EVAL_RUNNER || 'ubuntu-latest' }}`.
  Preflight checks LLM secrets **and** data (`make eval-validate-all --require-present`); if either is missing,
  write "skipped: <reason>" to `$GITHUB_STEP_SUMMARY` and exit 0. Otherwise smoke → gate → summary, and comment on the PR
  (`permissions: pull-requests: write`). Never print secrets.

### 2.7 Docs
- `docs/RESULTS.md`: add a generated block (`<!-- STATS:START/END -->`, written by `make results`) with k/n, rate,
  95% CI and, for 0/n, both upper bounds. Existing handwritten numbers stay; tests fail on a stale block, like the README block.
- `docs/EVAL_PLATFORM.md`: add an eval set, bump a version, read a run record, how CIs and verdicts are computed,
  gate rules, read a compare report, legacy reports list, why CI skips on hosted runners.

## 3. Order of work (eval first)

1. Preconditions (§0). Read `eval/compare.py`, `eval/e2e_records.py`, `eval/metrics.py`, `eval/sweep.py`,
   `eval/judge.py`, `scripts/render_results.py`, `.github/workflows/ci.yml`, and list `eval/sets/` and `eval/runs/`.
2. `eval/stats.py` + tests → `make check`.
3. Registry + `eval-validate-all` + bump command + tests.
4. Run-record models + `.gitignore` + migrate the five core scripts + tests.
5. Legacy import, regenerate v1 reports, prove "no change" with `eval-compare`.
6. Extended `eval-compare` (run dirs, CIs, McNemar, verdict).
7. Judge calibration.
8. Smoke builder, gate rules, `eval/gate.py`, `eval-baseline` guard + tests.
9. Workflow; lint it with `actionlint` if installed (otherwise say it was not linted).
10. RESULTS generated block, `docs/EVAL_PLATFORM.md`, Makefile targets (+ `.PHONY`).
11. `make check`, `docs/PROGRESS.md` (row 17 + known issues), note `docs/notes/17-eval-platform-ci.md`,
    `make notes-check`, one commit with the message from the task prompt. Include this plan file. Do not push.

## 4. Tests (all offline, in `make check`)

- Bootstrap: 95% CI of the mean on a seeded Bernoulli(0.3) sample of 200 contains 0.3; same seed → identical interval.
- Rule of three: 0/30 → 0.10, 0/60 → 0.05. Wilson upper for 0/30 ≈ 0.1135, for 0/60 ≈ 0.0602.
- McNemar exact: discordant b = 10, c = 2 → p = 158/4096 ≈ 0.0386; b = c → p = 1.0.
- Kappa on a hand-made 2×2 table with a known value; perfect agreement → 1.0.
- Paired bootstrap: identical runs → delta 0, verdict `no significant change`.
- Gate fixtures: one no-answer accepted → fail; 20 answerable items flip to rejected → `worse` → fail;
  2 items flip either way → pass; missing baseline → exit 2.
- Registry: changed file with the same version → fail; absent file → skip; `--require-present` + absent → fail; bump without version change → refused.
- Run records: round trip; refuse overwrite; manifest has every required field.
- Legacy import: a fixture JSONL imports to identical metrics.
- `eval-baseline` refuses off `main` and on a dirty tree (mock the git calls).
- Smoke builder: test split only, 30 + 40, stratified, same seed → same IDs.

## 5. Left for the human after this commit (put these in the final message)

1. Push the branch, open a PR, add the `run-evals` label, and check the job summary says "skipped" (or runs, on a self-hosted runner).
2. After merge, on `main`: `make eval-smoke-build`, `make eval-smoke`, `make eval-gate` (expect "no baseline"),
   `make eval-baseline RUN=…`, then commit `eval/baselines/main.json` as `chore(eval): promote first smoke baseline`.
3. Label at least 30 rows of `eval/sets/judge_calibration.csv`, then re-run `make eval-judge-calibration`.

## 6. Do not

- Do not call an LLM, Milvus or the reranker in tests, or re-run any model to "recreate" a legacy number.
- Do not commit question text, answers, `items.jsonl`, `smoke.jsonl` or calibration CSVs.
- Do not tune anything on the smoke set or the test split.
- Do not change gate thresholds, eval questions or labels.
- Do not invent human labels or a baseline.
