# Commit 23b plan — policy version evidence

Branch `codex/c23-policy-versions`, after `94c1254`. Commit message:
`chore(eval): policy version evidence`. This commit adds evidence, one small LLM evaluator
(§3.6) and docs. It changes no retrieval, gate or graph behaviour. If a step shows a bug,
stop, report it, and fix it in a separate `fix(...)` commit with a test before continuing.

## 0. Environment (read before running anything)

- Milvus 2.5.10 is remote, reached at `127.0.0.1:19530` through an SSH tunnel that the author
  keeps up. It drops for seconds to minutes. Release-evidence runs retry per question
  (`index.release.retry`). Other evals do not. If a run ends with transport errors, rerun it;
  never patch rows.
- Postgres for Atlas is `127.0.0.1:5433`. Never use port 5432. The dev registry and orders are
  in SQLite `data/orders.sqlite`.
- Never print `.env` values. Never push.
- Use the MPS reranker for every retrieval run:
  `SUPPORT_AGENT__RETRIEVAL__RERANKER_DEVICE=mps` (or `INDEX_ARGS=--reranker-device=mps` for
  index commands) and `HF_HUB_OFFLINE=1`. Device is part of every evidence hash, so never pair
  a CPU run with an MPS run.
- The rerank score cache `.cache/rerank_scores/scores.sqlite` is already warm (11,006 MPS pairs
  from the 22c measurement). Keep it.
- **Clean tree rule.** A run records `dirty` from `git status --porcelain` at its start.
  Before every run, the tree must be clean. After each run, move its new output directory
  under `eval/runs/` (if not gitignored) to `/tmp/atlas-23b/` and copy everything back only
  for the final commit. Never edit repo files while a run is collecting.
  `.git/info/exclude` already hides the author's untracked `visualizer.html` and `.claude/worktrees/`.
  This plan file is untracked too: move it to `/tmp/atlas-23b/` before the first run and copy it
  back for the final commit, so it does not make the runs dirty.
- Never drop or modify `support_chunks` or `support_chunks_faq_v1`. Do not run
  `make index-gc --yes`. The retrieval experiment builder (`make eval-retrieval` with ablations)
  may rebuild its own two collections, `support_chunks_eval_heading_on` and
  `support_chunks_eval_no_heading`: that is what they are for, and schema 2 requires it.
  Record that they were rebuilt. (Corrected after the first 23b attempt.)
- Before running anything, the frozen-label fix in §1a must be committed.

## 1a. Frozen-label check (added after the first attempt stopped)

`eval/validate_set.py::validate_current` hashes every section and compares it with the corpus
hash in `eval/sets/manifest.json`. The two synthetic historical sections make it fail, although
every section that existed when the labels were frozen is unchanged: hashing the sections
without the two `@2026-01-01` ids reproduces the frozen hash exactly. Fix it in its own commit
before any measurement, with tests (see the prompt). Do not edit `manifest.json`.

## 1. Data

1. `cp data/orders.sqlite /tmp/atlas-23b/orders.sqlite.before-23b` (registry and orders backup).
2. `make data-docs` (`policy_versions.enabled` is true). Expect 124 validated sections.
3. `make data-orders` to add the eight dated fixture orders. This reseeds orders and refund
   tables in the dev SQLite; the registry tables must survive. Check with `make index-status`
   that the alias still targets `support_chunks_bf66917e90d854635a44dbdac16e6e4c1` and drift is
   false. If the registry was lost, stop and restore the backup.
4. `make eval-time-sensitive-build` and `make eval-validate-all`.

## 2. Index (the eval_v1 no-regression check)

1. `make index-plan` and save the JSON: expect 2 added sections (the `@2026-01-01` versions),
   metadata changes on the rest, and mode `full` (schema 2 changes the fingerprint).
2. `make index-build INDEX_ARGS=--full`. Save the build JSON.
3. `make index-release BUILD=<id> INDEX_ARGS="--reranker-device=mps --output /tmp/atlas-23b/release.md"`.
   The live side is the legacy build, searched unfiltered (`filters_applied=false`); the
   candidate is filtered. This is the paired eval_v1 check on dev + smoke.
   - Release: keep the alias on the new build for the rest of 23b.
   - Refuse or invalid: stop and report. Do not override.

## 3. Measurements (all on the new build)

1. **Time-sensitive retrieval, no LLM.** `make eval-time-sensitive` with
   `TIME_SENSITIVE_ARGS="--split all --filters off"`, then `--filters date`, then
   `--filters date_category`. Pair off vs date_category per split with `make eval-compare`
   (McNemar on `version_hit_at_5` and `wrong_version_at_5`). Report test as the result;
   dev is shown but nothing is tuned.
2. **eval_v1 retrieval ablation.** `make eval-retrieval SPLIT=all` with MPS. It adds the three
   filter rows next to the existing modes. Report the filter rows against the unfiltered row.
3. **Refund policy retrieval.** `make eval-refund-policy`. Record how many orders now retrieve
   the historical version and whether gate outcomes changed against `eval/reports/refund_policy.md`
   at its committed revision (show both).
4. **Refund decisions (LLM).** `make eval-refund-decisions` with the default repeats. List the
   window-holdout orders whose expected answer changed because of the order date (computed,
   not edited). Compare with the committed `eval/reports/refund_decisions.md`; these are not
   paired runs, say so.
5. **Red-team (LLM).** Full v2 test split:
   `make eval-redteam EVAL_REDTEAM_ARGS="--dataset redteam_v2 --split test"`, then
   `make eval-compare A=eval/runs/redteam-test-20261121-b7d761af-ec53deb3 B=<new run>`.
   First check whether any red-team fixture order is dated before 2026-09-01 and say so.
6. **Refund path end to end (LLM).** Add `eval/time_sensitive_e2e.py` and a Make target. It runs
   the real graph for every `path: refund` item in eval_v2 (both splits, 8 items) as
   `CUST-TS01`, `ENV=dev`, scratch checkpoints, and a scratch copy of the orders database.
   Per item it records: route, decision, cited section ids, whether the cited version matches
   `gold_sections`, and whether the historical notice appears. Expected: notice on the
   historical-version orders only. Write a run record and a small report. Add an offline test
   with a fake graph. Do not change prompts or decision code to make it pass.
7. **Milvus integration.** `make test-milvus` plus
   `uv run pytest -m integration tests/test_index_freshness_integration.py -q` (SQLite registry),
   and once more with `ATLAS_TEST_PG_URL` pointing at a scratch database on 5433.

## 4. Report and commit

- `eval/reports/time_sensitive.md` from the saved runs (`--report-from`).
- `eval/reports/policy_versions.md`, generated by a script from the run records and saved JSON,
  never typed: data and index facts, the release decision, the time-sensitive tables with CIs,
  the ablation rows, the refund and red-team comparisons, the end-to-end table, and integration
  results. Name every run directory. State limits: synthetic versions of two sections, 4 refund
  dates per split, unreviewed labels.
- Commit run manifests and metrics the way earlier evidence commits did (force-add only what
  `.gitignore` hides by design). Never commit `.sqlite`, `.env` or per-item rows that hold
  question text where the repo keeps them local.
- PROGRESS: row 23b, a "Commit 23b verification" section, known issues. Interview note
  `docs/notes/23-policy-version-evidence.md` with real numbers and their report path.
- `make check`, then one commit. Final message: what ran, each number with its source,
  deviations, failed or rerun attempts, follow-ups, then the full interview note.
