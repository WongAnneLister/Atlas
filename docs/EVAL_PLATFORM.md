# Evaluation platform

Use dev to choose settings. Test and smoke measure the frozen choice. The smoke
set contains all test no-answer items and a seeded sample from each answerable
group. Its source version and selected IDs are in [smoke.yaml](../eval/smoke.yaml).

## Register a dataset

1. Put the frozen JSONL in `eval/sets/`. Each row needs a unique `id` and a
   `split`. Use `reviewed: true` only for a human-reviewed row.
2. Add an entry to [registry.yaml](../eval/registry.yaml) with its name, path,
   initial version, byte-level SHA-256, item and split counts, reviewed count,
   license scope, and initial changelog entry. Keep mixed-license text local.
3. Run `make eval-validate-all`. Missing local files are skipped. Use
   `make eval-validate-all EVAL_VALIDATE_ALL_ARGS=--require-present` when all
   datasets should exist. Changed hashes fail even when local files may be absent.
4. For an intentional dataset change, run
   `make eval-registry-bump NAME=<dataset> VERSION=<new-vN> NOTE='<reason>'`.
   Commit the registry update with the source or builder change. A new smoke
   version needs a corresponding frozen ID spec and a fresh baseline on main.

`make eval-smoke-build` materializes the ignored smoke JSONL. It checks the source
and output hashes against the registry and reuses the saved IDs.

## Save and read a run

The normal v1 targets still generate their reports. Each completed evaluation
writes `eval/runs/<run_id>/` containing these files.

| File | Contents |
|---|---|
| `manifest.json` | Git SHA and working tree state, config hash, model names, dataset hashes and versions, split, seed, UTC times, cost, and command |
| `items.jsonl` | Local per-item results, with the detail needed to replay the report |
| `metrics.json` | Publishable aggregate metrics, intervals, counts and zero-event bounds |

Commit the manifest and metrics where they support a reported result.
Generated smoke runs stay local so the working tree stays clean for promotion. The per-item
file is ignored because it can contain licensed text. Historical records leave
fields null when the original source lacks the measurement. Comparison and replay
require the local item file or the original source for import.

```sh
make eval-import-legacy EVAL_IMPORT_ARGS='--suffix replay e2e eval/runs/e2e-test-c15.jsonl'
make eval-e2e EVAL_E2E_ARGS='--run-dir eval/runs/e2e-test-20261117-266c1e85-replay'
make eval-compare A=eval/runs/e2e-test-c15.jsonl B=eval/runs/e2e-test-20261117-266c1e85-replay
make results
```

[The migration replay](../eval/reports/commit17_replay.md) shows the current E2E comparison.

Use `make eval-import-legacy EVAL_IMPORT_ARGS=--help` to see the supported
formats. Intent and retrieval use their saved full-run caches. Sweep takes the
dev and test score files and the original selection rule. Retrieval CSVs
reconstruct numeric results and paired observations. Full retrieval replay uses
the original cache for diagnostics. The judge import takes the review CSV and its
source E2E run. The archived `e2e-001` reports and checksums stay frozen.

The remaining historical experiments keep their original formats. These include
data-build, ingestion, order-seed, routing and coverage, near-miss and store
controls, gate round three, chunking, tool fallback, order grounding and replies,
safety fixes, model veto, and refund policy and decision reports.

## Faster real-model runs

A real-model end-to-end item takes about 17 seconds. Most of it is four or five
sequential LLM calls and one cross-encoder rerank. `eval/e2e_eval.py` (and so
`make eval-smoke`) and `eval/multipart_eval.py` have two opt-in speed-ups. Neither
changes a measured value, so both stay out of the run's config hash.

| Switch | Config | CLI | Make |
|---|---|---|---|
| Rerank score cache | `eval.e2e_speed.rerank_cache` (default `false`) | `--rerank-cache` / `--no-rerank-cache` | `EVAL_RERANK_CACHE=1` |
| Item workers | upper bound `eval.e2e_speed.max_workers` | `--workers N` (default 1) | `EVAL_WORKERS=N` |

```sh
make eval-multipart EVAL_WORKERS=4 EVAL_RERANK_CACHE=1 MULTIPART_ARGS='--split test'
make eval-e2e EVAL_RERANK_CACHE=1 EVAL_E2E_ARGS='--split test --fresh'
```

- The cache is the release-evidence file, `index.release.rerank_cache.path`, with
  the same key: reranker model, revision, device, fp16, max tokens, batch size, the
  installed versions of `key_packages`, the query text and the passage text hash.
  A score scored in one run is read back by any later run, release or end-to-end.
  The manifest's `source.rerank_scores` records the file, the key profile and how
  many logits came from the cache (`from_cache`) or the model (`scored`).
  As in commit 22c, a pair scored in a smaller batch can differ by float noise
  (at most 7.13e-09 in [the release measurement](../eval/reports/rerank_cache.md)).
- Workers share one graph: one reranker worker and the LLM API. The saved items stay
  in input order, so a run never depends on which item finished first. Each item's
  latency then includes time spent waiting for the others. The manifest records
  `source.workers` and `source.latency_comparable: false`, the report marks each
  latency as not comparable, and `make eval-compare` and `make eval-gate` leave
  latency out with a note. `make eval-baseline` refuses such a run.
- A queued rerank call waits inside its own `reliability.timeouts_s.rerank` deadline.
  Keep `N` small enough that a queue of reranks cannot reach it. A timed-out rerank on
  the knowledge path hands off and sets `retrieval_error_type`, which the gate's
  dependency-error check counts, so it shows up rather than passing silently.
- Chaos runs refuse both switches: their seeded faults follow call order.
- A resumed `e2e_eval` output keeps the largest worker count it has seen and adds up
  its cache counts.

## Interpret a comparison

Read the paired item count first. General comparisons use shared IDs, display
unmatched item counts, and use only items with both observations for each metric.
The release gate requires matching dataset versions, IDs, labels, and metric
observations.

A percentile bootstrap resamples items with replacement. The default uses
2,000 resamples, a fixed seed, and the middle 95% of the resulting statistics.
For P95 latency it recomputes the percentile within each resample. For a paired
difference it resamples the same item indices in A and B. The reported delta is
B minus A.

A zero observed count can yield a zero-width bootstrap interval. The reports
also show the rule-of-three approximation and the two-sided Wilson interval's
upper endpoint for zero observed events. The counts are what the run observed.

For binary outcomes, the exact McNemar test uses only pairs whose outcomes
disagree. A verdict uses its p-value at the configured significance level.
For continuous metrics the paired interval must exclude zero. The metric's
configured direction determines whether a significant change is better or worse.
“No significant change” means the test did not detect a difference.

## Calibrate the judge

Run `make eval-judge-calibration` to refresh the local review sample and its
report. The tool keeps all audited flags and a seeded sample of audited unflagged
rows. Mark the local `human_label` column `yes` for an unsupported claim or
`no` for a supported answer. Rerun to compute precision, recall, and Cohen's
kappa, an agreement score adjusted for chance. Agreement describes the labelled
sample. Oversampling flags changes the sample mix. The report shows how many
labels are missing when the minimum has yet to be reached.

## Run and promote the release gate

```sh
make eval-smoke
make eval-gate RUN=eval/runs/<smoke-run-id>
make eval-baseline RUN=eval/runs/<smoke-run-id>
```

The gate rejects any no-answer false accept and any significant regression in
[gate_rules.yaml](../eval/gate_rules.yaml). A metric with `blocking: false` (currently only
`latency_p95`, which depends on the runner and the SSH tunnel) is reported as a
warning instead of failing the gate. The red-team rules will be added with
their eval set. The gate CLI returns 1 on failure and 2 when the main baseline is
missing. Promote from a clean `main` checkout using a run collected on its
current HEAD. Promotion also refuses a run where more than
`promotion_max_error_rate` of items hit a classification, retrieval or answer error
(an outage, a dropped tunnel or an empty API balance), because such a run would
make every later run look better than it is. `make eval-gate` applies the same rate: such a run fails with an "Invalid run: dependency errors on X/N items" line before any metric comparison, so an outage is not mistaken for a regression. Commit `eval/baselines/main.json` after promotion. The baseline
stores IDs, scalar outcomes and metadata. The first baseline is created after the
platform lands on main.

The workflow runs nightly, on demand, and on same-repository PRs with the
`run-evals` label. It reports skip reasons and gate results in the job summary.
Configure `EVAL_RUNNER` with a runner label for the trusted environment that
contains the local datasets, manifests, orders, model caches, and access to the
Milvus index. The runner needs the LLM model settings and provider key listed in
`.env.example`. Fork PRs skip evaluation. A runner with missing inputs reports a
skip. A dataset integrity failure fails the job. The CI comparison reads the
baseline from `origin/main`.
