# Full test regression, 2026-11-28 — plan (written before any run)

Purpose: measure the current `main` on the test split after the changes since the last
full test runs (answer budget, oversized-chunk split and local index, refund decision v4,
classifier rounds 12h and 13e). This is a measurement, not a tuning step.

## Runs (one each, in a clean worktree at the commit that adds this file)

1. `eval.e2e_eval --split test` on `eval_v1` (150 items), `--workers 3 --rerank-cache`,
   answer cache off, scratch copy of the orders DB, local Milvus `support_chunks_live`.
2. `eval.sim.run --split test --subset all --repeats 3` (30 scenarios, 90 conversations),
   scratch copy of the orders DB, with the validity report.

## Baselines

- e2e: `eval/reports/e2e.md` (`266c1e8`, 2026-11-17, the README headline) and the latest
  test run `e2e-test-20261126-a15a011e-07795716` (paired with `make eval-compare`).
  Latency is not comparable with either: both used Milvus on the VPS.
- sim: no full-test run exists. The nightly scenarios are compared by scenario with
  `sim-test-20261127-2112c54f` (`eval/reports/sim.md`); the nine refund scenarios with the
  12h test run `sim-all-20261128-c4ffe38a`.

## Rules

- Nothing is tuned on these results. Numbers are reported as measured, misses included.
- A run refused by the run-health guard (exit 3) is not reported. The cause is fixed
  outside the agent code, the refused run is recorded here, and the run is repeated.
- If any no-answer item is falsely accepted, that is recorded as a safety-gate failure.
  The gate threshold is not changed in this round.
- The new runs replace `eval/reports/e2e.md`, `sim.md` and `sim_validity.md`; the old
  reports move to `eval/reports/archive/` and the notes that cite them are repointed.

## Run log

- e2e at `ab6c1e4`, clean, exit 0: run `e2e-test-20261128-ab6c1e41-5569cbf6`.
- sim at `ab6c1e4`, clean, **voided** (exit 1 after 31 minutes, no report): one
  simulated-customer call hit an SSL drop (`EOF occurred in violation of protocol`) that
  outlasted the agent's retry policy (3 attempts, delays up to 1 s), which the simulator
  borrowed. Fixed in the harness only: the simulator now has its own policy,
  `eval.sim.retry` (6 attempts, delays up to 30 s). Agent code and agent retries are
  unchanged. The sim run is repeated at the fix commit; the e2e run is kept.
