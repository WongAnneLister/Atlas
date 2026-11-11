# Evidence coverage optimization, round two

## Scope and decision

The user approved a correction to the existing knowledge answer path after routing round one.
Classification, retrieval, model roles, evidence weights, and threshold remain unchanged.
The existing evidence gate still runs before every knowledge answer.
This is not the phase-two claim-grounding platform or a general reliability framework.
Refund and tool answer semantics remain outside this experiment.

The original answer prompt permits partial answers followed by an offer of human help.
Its code accepts any nonempty answer with a valid citation number.
That can leave a substantive answer without a real handoff when important facts are missing.

The candidate uses one structured main-model call to list requested parts and source evidence.
Each supported part contains an answer, source numbers, and exact source quotes.
Code checks quote membership and source bounds, then adds citation numbers itself.
Any unsupported part creates a real handoff instead of releasing the partial draft.
Invalid structured output, invalid evidence, and dependency failures also fail closed.
This replaces the existing answer call; it does not add a second judge call.
Structured output and quotes can still change latency and token use.

The model can omit a requested part or misjudge whether a quote supports a claim.
Exact quote membership proves provenance, not entailment, factual accuracy, or complete decomposition.
Prompt instructions address those risks, but do not eliminate them.
Human review remains required.

## Failure diagnostics

New graph and E2E fields separate classifier failures, retrieval errors, answer errors,
invalid output, invalid evidence, coverage rejection, and successful answers.
Handoff reasons distinguish retrieval failure, answer failure, invalid answer, and incomplete evidence.
The operator payload retains the coverage decision alongside the conversation and retrieval snapshot.
Per-turn reset clears the new fields so errors do not leak into later turns.
Older run rows load with unknown diagnostic fields, not invented successful-call flags.
Gate rejection without retrieval error is counted only on newly instrumented knowledge rows.
Refund retrieval is not instrumented by this correction.

E2E cache checks now include code, prompt, model, runtime, and frozen item contents.
Atomic per-item writes preserve progress; compatible resumes retain the original collection date.
Use a fresh output when implementation or prompts change.
The optional E2E `--report` path preserves archived/default reports during experiments.

## Evaluation design

`make eval-coverage` freezes inputs before inference in a local ignored JSONL file.
It uses original `hybrid_rerank` dev retrieval contexts plus original fictional control passages.
The controls cover full support, partial support, and related content without an answer.
Their dev/test split was fixed before any original or candidate inference.
Test controls use different fictional store topics and product facts from dev controls.
They are authored, unreviewed checks, not a representative blind corpus benchmark.
The old full-test split has already been observed and is treated as regression only.
No original question, answer point, gold section, review flag, or threshold was changed.

The answer-stage experiment feeds identical fixed contexts through the same gate and answer code.
It deliberately excludes intent routing, live retrieval, embedding, and reranking latency.
It cannot establish end-to-end task success or production answer accuracy.
Original dev labels describe corpus answerability, not complete coverage by a particular top-five context.
Some colloquial questions include additional requests in their source prefixes.
The candidate can reject those extra requests even when the frozen gold only covers the FAQ part.
Keep the original labels and report this limitation rather than silently ignoring question text.

An initial run inside the restricted sandbox encountered DNS failures and was stopped.
Its partial rows remain under `eval/runs/coverage-round2-before-dev.jsonl`.
The reported original dev run is a separate complete fresh run with working network access.
It is not a collection that selectively replaced failed questions.
Original and candidate calls retain failures and preserve their collection metadata.

Dev collection exposed reporting/cache integrity improvements found during code review.
Report-only rendering now rejects incomplete, duplicate, altered-input, or mismatched-split rows.
Cache code hashes include shared gate/model code and the frozen legacy answer implementation.
These changes followed dev collection and do not rewrite saved row metadata or outcomes.
Report regeneration uses saved metadata; production file hashes supplement collection provenance.
Reports show n/a when a subset has no denominator for a false-accept or false-reject rate.
The combined summary reuses complete frozen-input validation for both coverage runs.
It also rejects duplicate full-graph rows before indexing and verifies the full frozen test set.
Offline regression tests cover truncated, duplicated, and altered summary inputs.
Configured provider aliases can change behind the same model name; they do not pin model weights.

## Reproduction

Load `.env` with `python-dotenv` as described in `docs/RESULTS.md`.
Makefile coverage targets load it themselves. Full graph targets read process environment.
The original free-text behavior is retained only in `eval/legacy_knowledge.py`.
Its saved prompt is `eval/prompts/coverage_round2_before.md`.
The legacy implementation reproduces the old acceptance rule with diagnostic fields added.

```bash
make eval-coverage EVAL_COVERAGE_ARGS='--freeze --inputs eval/runs/coverage-repro-inputs.jsonl'
make eval-coverage EVAL_COVERAGE_ARGS='--inputs eval/runs/coverage-repro-inputs.jsonl --split dev --legacy --output eval/runs/coverage-repro-before.jsonl --report eval/reports/coverage_repro_before.md'
make eval-coverage EVAL_COVERAGE_ARGS='--inputs eval/runs/coverage-repro-inputs.jsonl --split dev --output eval/runs/coverage-repro-after.jsonl --report eval/reports/coverage_repro.md --baseline eval/runs/coverage-repro-before.jsonl'
```

Use a new output path for a rerun; never overwrite a frozen run to improve a result.
`--report-only` renders complete saved rows without model calls or changing collection metadata.
Actual collection hashes identify the code used at that time, not the later reporting code.

The pre-test production freeze is in `eval/reports/coverage_round2_manifest.json`.
Its production file map is checked before full-graph regression and after collection.
The candidate remains frozen after dev, regardless of test results.
Reports contain provenance, metrics, and ids; source text and full predictions stay ignored locally.

## Completed regression and interpretation

The complete result is in `eval/reports/coverage_round2_test.md`.
`make eval-coverage-summary` rebuilds the combined summary and bar chart from saved runs.
`eval/reports/coverage_round2_compare.md` lists every changed acceptance outcome by id.
The production map still matches the pre-test freeze after all inference completed.
The manifest completion section adds artifact checksums without changing that freeze.

The previously accepted no-answer payment case now creates an incomplete-evidence handoff.
The net answerable rejection count increased, and individual routes changed in both directions.
The classifier prompt did not change; provider aliases and calls are not fully deterministic.
The prior full-graph run included connection failures; this one recorded no classifier,
retrieval, or knowledge-generation invocation failures.
The full-graph latency improvement cannot be attributed entirely to structured coverage.
The fixed-context control test actually increased answer-stage P95 latency.
See `docs/RESULTS.md` for the measured values and remaining human-review requirements.

The pre-test manifest retained an earlier Asia/Tokyo client annotation.
Collection timestamps are the recorded UTC values; the current workspace timezone is America/Denver.
Neither annotation changes the ordering of the saved freeze and inference timestamps.
