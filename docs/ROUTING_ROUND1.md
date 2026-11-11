# Routing optimization round one

This experiment changes only `graph/prompts/classify.md` in the application.
It distinguishes explanations and self-service guidance from order lookups and requested actions.
Intent mappings, models, tools, retrieval, evidence signals, and the gate threshold remain unchanged.

## Evidence and selection

The first full baseline showed answerable questions routed to fixed, order, and refund paths.
The old prompt also treated shipping options as tool work and account topics as unsupported actions.
The dev questions include policy and self-service guidance on those topics.

The original prompt was measured before editing the application prompt.
All dev questions were used, accompanied by controls authored before either run.
The reports do not invent intent labels for no-answer questions.
Answerable retrieval questions target knowledge path B by benchmark construction.
Some personally worded questions remain ambiguous; these are not human-reviewed intent labels.
Questions and labels were not changed.

See `eval/reports/routing_round1.md` for generated paired dev measurements and provenance.
It retains original invocation failures and also shows paired successful calls separately.
No original failed calls were selectively rerun.
The controls cover informational versus operational requests, greetings, complaints, and human requests.
Controls are boundary checks, not a representative held-out intent benchmark.
The earlier full intent holdout was not rerun in this experiment.
Its existing loader binds dataset construction to the original selection prompt.
Do not rebuild that holdout silently or compare a newly sampled set as identical data.

After the measured dev improvement and successful controls, the candidate was frozen.
`eval/reports/routing_round1_manifest.json` records the candidate fingerprint before test inference.
Original and candidate prompts are preserved in `eval/prompts/routing_round1_before.md`
and `eval/prompts/routing_round1_after.md`.
No test result is used to revise this round's candidate.

## Reproduction

Load the local `.env` into the process environment as shown in `docs/RESULTS.md`.
The routing experiment needs only the fast model, without Milvus or embedding models.
Choose fresh output paths after code, prompt, model, or configuration changes.

```bash
make eval-routing EVAL_ROUTING_ARGS='--prompt eval/prompts/routing_round1_before.md --output eval/runs/routing-repro-before.jsonl --report eval/reports/routing_repro_before.md'
make eval-routing EVAL_ROUTING_ARGS='--prompt eval/prompts/routing_round1_after.md --output eval/runs/routing-repro-after.jsonl --report eval/reports/routing_repro.md --baseline eval/runs/routing-repro-before.jsonl'
```

The saved original measurements can regenerate their report without API calls:

```bash
make eval-routing EVAL_ROUTING_ARGS='--prompt eval/prompts/routing_round1_after.md --output eval/runs/routing-round1-after.jsonl --report eval/reports/routing_round1.md --baseline eval/runs/routing-round1-before.jsonl --report-only'
```

Report-only mode describes saved measurement metadata; it does not claim the current code ran inference.
The first report-rendering attempt exposed a cross-module Pydantic class comparison issue.
The comparison now checks serialized item contents; the saved measurement rows remain unchanged.
Recorded collection code hashes precede these reporting-only fixes.

The full graph uses `eval/runs/routing-round1-test.jsonl` as a fresh candidate output.
The original baseline remains `eval/runs/baseline-001-e2e-test.jsonl`.
The candidate completed the full test split. Generate the comparison with:

```bash
make eval-compare A=eval/runs/baseline-001-e2e-test.jsonl B=eval/runs/routing-round1-test.jsonl EVAL_COMPARE_ARGS='--output eval/reports/routing_round1_compare.md'
```

Full question text and predictions stay local under the existing mixed-source license restrictions.
Committed reports contain provenance, counts, metrics, and item identifiers.

## Interpretation

Better routing does not establish correct answers or stronger evidence coverage.
This round does not repair the Cash App Pay evidence gap or change the gate calibration.
All final graph outcomes, including dependency failures, remain in the candidate run.
The baseline shared compute with sweep collection and had SSH outages.
The candidate full-graph evaluation runs separately with an SSH reconnect supervisor.
Latency and dependency-related acceptance changes cannot be attributed solely to the prompt.
Candidate judge flags and human-confirmed accuracy are not measured by the routing experiment.

The reviewer noted an overlap between the retained individual-return example and the new guidance rule.
Keep the candidate frozen; investigate such ambiguity on dev in a later experiment.

## Full-test result

`eval/reports/routing_round1_test.md` records the complete candidate run.
`eval/reports/routing_round1_compare.md` compares its unchanged test items with the frozen baseline.
`docs/RESULTS.md` presents the before/after table.
Routing improved on dev, and answerable rejection decreased on the full test set.
The same no-answer false accept remains; this round did not clear the safety checkpoint.
Do not interpret acceptance or citation overlap as answer accuracy.

The candidate execution log records connection errors in classification and answer generation.
Some fixed replies reflect classifier fallback rather than a semantic routing decision.
Some knowledge handoffs followed a passing gate, then failed during the answer stage.
The current `low_evidence` reason conflates evidence rejection and answer failure.
The E2E schema does not retain the classifier error fields available in graph state.
Keep these limitations visible; add diagnostic fields in a separately measured change.

Checks confirmed identical item contents, unique ids, models, config, corpus, and threshold.
All frozen baseline artifact checksums still match.
The candidate prompt remained unchanged throughout test inference.
Final artifact checksums are recorded separately from the pre-test freeze in the round manifest.
