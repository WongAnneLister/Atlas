# Evidence coverage round two

The user approved the proposed diagnostic and coverage optimization.
This is a bounded correction to the existing phase-one knowledge answer path.
It does not introduce the phase-two claim-grounding platform.

**Goal:** Measure whether explicit source coverage prevents substantive unsupported answers.

**Design:** Keep classification, retrieval, models, gate weights, and threshold unchanged.
The existing evidence gate must pass before answer generation.
One structured main-model call lists every requested part, its support, answer, and source quotes.
Code checks source numbers and verbatim quotes, then builds citations itself.
Any unsupported part, invalid output, invalid evidence, or model failure creates a real handoff.
This remains a model coverage judgment; quote presence alone does not prove entailment.

## Work items

- [x] Add offline failing tests for precise knowledge errors and E2E diagnostic persistence.
  Update `graph/state.py`, `nodes/knowledge.py`, handoff reasons/templates, and rewrite resets.
  Preserve the legacy answer behavior until its paired dev measurement is complete.
- [x] Add an answer-stage experiment under `eval/`, with a Makefile target.
  Freeze original dev retrieval contexts and authored support/partial/absent controls before calls.
  Keep controls independent of known old test questions; freeze control dev/test splits up front.
  Record settings, source/prompt/input hashes, models, versions, dates, original failures, and latency.
  Use atomic per-item checkpoints; reject changed or duplicate cached inputs.
- [x] Run the original answer path on identical dev contexts and dev controls.
  Do not inspect fresh test-control predictions during candidate development.
- [x] Add failing graph tests for partial coverage, invalid source quotes, missing gate,
  invalid output, supported answers, exceptions, and state reset across turns.
  Implement typed parts/quotes and fail-closed answer rendering in `graph/coverage.py`.
  Replace `graph/prompts/answer.md`; keep the old prompt under `eval/prompts/`.
- [x] Run the candidate on the same dev contexts. Report safety and rejection costs honestly.
  Freeze the candidate after dev; then run the untouched control test and old full-test regression.
  The old full test has already been observed; it is regression evidence, not a new blind test.
  Controls have authored, unreviewed labels and do not establish production accuracy.
- [x] Update `docs/PROGRESS.md`, `docs/RESULTS.md`, methodology, and the interview note.
  Run `make check`, `make notes-check`, and `git diff --check`; request code review.
  Make one local Conventional Commit; do not push without a new request.
  Final verification and the local commit are recorded in the commit containing this plan.

## Verification commands

Use `make test TEST_ARGS='tests/test_graph_knowledge.py tests/test_eval_tools.py -q'`
for the diagnostic regression and the later coverage tests.
Use `make eval-coverage EVAL_COVERAGE_ARGS='...'` for paired answer-stage measurements.
Use `make eval-e2e EVAL_E2E_ARGS='--split test --output eval/runs/coverage-round2-test.jsonl --report eval/reports/coverage_round2_test.md'`
for the frozen candidate full-graph regression. Preserve existing default reports.
Use `make eval-compare A=eval/runs/routing-round1-test.jsonl B=eval/runs/coverage-round2-test.jsonl`
with a distinct report output for the final comparison.
