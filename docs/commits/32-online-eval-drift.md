# Commit 32 — Online evaluation: feedback, sampled review, drift monitoring

**Phase 2 · Evals · depends on: 15, 17, 31**

## Context
Offline evals only cover the questions we thought of. Online signals tell us how the system behaves on real traffic:
explicit feedback, sampled human review, and drift in the signals we already compute (gate scores, intent mix, handoff rate).
This is the last piece of the eval stack: offline (17–27) + online (this) + human loop (31).

## Read first
- `docs/EVAL_PLATFORM.md`, `docs/OBSERVABILITY.md`, `docs/HANDOFF.md`, `observability/`

## Task
1. **Feedback** — thumbs up/down + optional reason on each AI answer in the chat page; `POST /api/feedback` (idempotent per message). Stored in Postgres and attached to the Langfuse trace as a score.
2. **Sampled review** — a nightly job samples N answered conversations (stratified by intent and gate-score bucket, oversampling scores near the threshold) into a review queue in the agent console with a rubric: correct / partially correct / wrong / should have handed off. Labels stored as eval candidates (same workflow as 31).
3. **Online automatic checks** (cheap, run on every answered turn or a sample): citation validity, claim-grounding verdicts (already computed), guardrail flags. Aggregate as time series.
4. **Drift monitoring** — `src/support_agent/observability/drift.py` + `make drift-report`:
   compare the last window vs a reference window (the eval baseline, or last week) for: intent distribution (PSI or chi-square), gate-score distribution (KS test / PSI), handoff rate by reason, rewrite-skip rate, average tokens per turn, cost per conversation, thumbs-down rate. Thresholds in config; breaches written to `eval/reports/drift.md` and exposed as Prometheus gauges.
5. **Traffic generator for the demo** — since there are no real users, `scripts/replay_traffic.py` replays a mix of scenarios and Bitext utterances over a simulated week (including a deliberate shift on "day 5", e.g. a surge of questions on a topic missing from the docs). Show that drift detection catches it and the loop report surfaces the doc gap. Clearly label this as simulated in README.
6. `docs/ONLINE_EVAL.md` — signals, how they map to actions (who looks, what threshold triggers what), and limitations.

## Requirements
- Online metrics never block requests (async writes, failures logged).
- No raw customer text in metrics labels; reviewers see redacted text unless they have the agent role.

## Tests
- PSI/KS helpers on known distributions; breach logic with thresholds.
- Feedback idempotency; sampling stratification on fixtures.

## Out of scope
Automatic retraining or automatic threshold changes — humans decide; thresholds still change only via the sweep + gate.

## Done when
- [ ] Simulated week report shows the day-5 shift detected and the doc gap surfaced
- [ ] `make check` green; PROGRESS row 32 updated
- [ ] Interview note `docs/notes/32-online-eval-drift.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(eval): online feedback, stratified sampled review, automatic online checks and drift monitoring
```
