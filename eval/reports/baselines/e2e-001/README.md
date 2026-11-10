# E2E baseline 001

This is the first complete real-model, test-split full-graph evaluation.
Earlier retrieval and intent evaluations measured separate components.
The full graph ran on test; dev was used for evidence analysis and threshold selection.
This is a failed safety baseline, not a release approval or measured answer accuracy.

Registered on 2026-11-11 in Asia/Tokyo.
Original run metadata starts at 2026-11-10T15:11:06.756261+00:00.
The archived E2E report has a later report-refresh timestamp.
Refreshing reports did not change measured item rows.

## Frozen artifacts

`manifest.json` records original provenance, effective environment, paths, and SHA-256 checksums.
The accompanying Markdown reports and PNG charts are byte copies of the first results.
`config.yaml` preserves the selected threshold and configuration at registration.
Environment overrides are listed separately in the manifest; credentials are excluded.

Measurements remain in the copied, script-generated reports:

- [`e2e.md`](e2e.md): full-graph acceptance, retrieval, citations, latency, and token results.
- [`threshold_sweep.md`](threshold_sweep.md): dev selection and held-out gate results.
- [`gate_signals_dev.md`](gate_signals_dev.md): dev evidence signal distributions.
- [`hallucination_review.md`](hallucination_review.md): judge flags and pending human confirmations.

Acceptance is not correctness. No aggregate answer-accuracy claim has been established.
The failed no-answer item ID and route are retained in `e2e.md`.
The human review CSV remains unconfirmed.

## Local records

The following copies remain gitignored because they contain mixed-license source text:

- `eval/runs/baseline-001-e2e-test.jsonl`: complete graph results, usable as compare input A.
- `eval/runs/baseline-001-gate-dev.jsonl`: dev scores used to choose the threshold.
- `eval/runs/baseline-001-gate-test.jsonl`: held-out test gate scores.
- `eval/runs/baseline-001-eval-set.jsonl`: frozen questions and labels.
- `eval/sets/baseline-001-hallucination-review.csv`: original judge rows without human confirmations.

These local copies are not included in a fresh clone or remote Git backup.
Keep them when cleaning local generated files.
Do not edit this archive; write future reports and human confirmations to new paths.

## Comparing the next change

Use the same frozen evaluation file, corpus, split, customer fixture, and outcome definitions.
Develop prompts, weights, and thresholds using dev only.
Give every candidate a new output filename so resumable evaluation cannot reuse baseline outcomes.
Load `.env`, establish the Milvus tunnel, and select the required runtime device as documented in `docs/RESULTS.md`.

```bash
make eval-e2e EVAL_E2E_ARGS='--split test --output eval/runs/candidate-002-test.jsonl'
make eval-compare A=eval/runs/baseline-001-e2e-test.jsonl B=eval/runs/candidate-002-test.jsonl EVAL_COMPARE_ARGS='--output eval/reports/e2e-001-vs-candidate-002.md'
```

The comparison reports acceptance deltas and changed item outcomes.
Inspect the candidate's E2E report separately for retrieval, citations, tokens, and latency.
Record all deliberate model, configuration, code, and infrastructure changes.
The comparison tool does not enforce matching provenance; check both headers before interpreting deltas.
If evaluation labels or corpus change, register a new benchmark version instead of claiming a like-for-like improvement.

## Limits retained with the baseline

Labels remain unreviewed drafts.
Sweep and E2E shared local resources; SSH outages caused retained fail-closed outcomes.
Latency is an operational observation, not an isolated performance reference.
Run a separate stable-environment baseline before attributing speed gains to an algorithm change.
The judge used the same model as generation and skipped answers without cited text.
First-token latency, verified cost estimates, and human-confirmed hallucination remain pending.
