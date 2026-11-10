# Commit 09 Graph and Intent Evaluation Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans. AGENTS.md requires one final commit, overriding intermediate skill commits.

**Goal:** Build fixed graph routing and measure real-model intent classification.

**Architecture:** Pydantic state flows through rewrite, structured classification, and one stub path. Code owns the nine-to-five mapping. A deterministic Bitext holdout and separately sourced extras judge classification.

**Tech Stack:** Python 3.11, LangGraph, LangChain, Pydantic, pytest, uv.

The authorized design is `docs/commits/09-graph-intents.md`. Real path logic and the evidence gate remain outside this commit.

## Contracts and configuration

- [ ] Write `tests/test_graph_intents.py` and a provider-options factory test; observe red with `make test TEST_ARGS='tests/test_graph_intents.py tests/test_llm.py'`.
- [ ] Implement `graph/intents.py` with exhaustive `Intent`, `Path`, `INTENT_TO_PATH`, and `PATH_NODES` contracts.
- [ ] Add typed graph/intent/eval settings in `graph/settings.py` and YAML; keep thresholds and limits configured.
- [ ] Pass provider kwargs through the sole model factory; verify the focused tests turn green.

```python
assert INTENT_TO_PATH[Intent.POLICY_QUESTION] == Path.KNOWLEDGE
assert set(INTENT_TO_PATH) == set(Intent)
```

## Graph implementation

- [ ] Add failing route tests for all intents, first-turn rewrite skip, bounded follow-up context, parse failure, confidence flags, persisted history, and cleared per-turn outputs.
- [ ] Implement `state.py`, `deps.py`, `nodes/rewrite.py`, `nodes/classify.py`, `build.py`, and separate prompt files.
- [ ] Use structured intent/confidence output; invalid classifications become fixed intent with zero confidence and a logged failure.
- [ ] Route through a pure conditional function. Trace is rewrite, classify, then the selected stub; stubs append their assistant message.
- [ ] Test memory checkpoints and optional SQLite lifecycle; no real model calls in unit tests.

## Evaluation inputs

- [ ] Test all 27 source labels, deterministic source-balanced sampling, normalized deduplication, holdout separation, and prompt/test exclusions before implementation.
- [ ] Implement `data/intent_map.py`, `eval/intent_records.py`, `eval/intent_data.py`, and authored extra drafts.
- [ ] Map neutral review/account operations to the fixed path and payment-problem reports to complaint, recording real-data reasons.
- [ ] Exclude Bitext rows already used in retrieval questions. Product extras use retrieval dev only; greetings and return extras retain authored provenance.
- [ ] Build ignored local JSONL/manifest artifacts; report short groups without duplicating examples.

## Measurement and completion

- [ ] Add hand-calculated metric and report tests, then implement `eval/intent_eval.py`, `eval/intent_report.py`, `make eval-intent-build`, and `make eval-intent`.
- [ ] Record accuracy, path accuracy, per-intent precision/recall, confusion matrix, failures, model identity, original timings, and full provenance hashes.
- [ ] Cache predictions by provenance. Load ignored model credentials only in the real CLI.
- [ ] Freeze prompt and benchmark before the full user-authorized DeepSeek run; report misses without tuning on the holdout.
- [ ] Review spec compliance, then code quality. Resolve concrete bugs with failing regression tests.
- [ ] Update `docs/INTENTS.md`, `docs/PROGRESS.md`, and `docs/notes/09-graph-intents.md` with honest results and limitations.
- [ ] Run `make check`, `make notes-check`, and `git diff --check` after final changes.
- [ ] Make one commit: `feat(graph): LangGraph skeleton with query rewrite and 9-intent classifier plus intent eval`.
- [ ] Keep the commit local unless asked to push; paste the full interview note in the final answer.
