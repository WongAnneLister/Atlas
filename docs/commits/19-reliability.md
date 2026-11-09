# Commit 19 — Reliability: timeouts, retries, fallback, fail-closed, idempotency, locks, metrics

**Phase 2 · depends on: 18**

## Context
LLM APIs time out, rate-limit, and return malformed output; the reranker can be slow; users double-click.
A production agent must degrade predictably. Key rule (AGENTS §5.7): **fail closed** — if a dependency the safety path
needs is down, hand off; never answer with weaker evidence than the gate was calibrated on.

## Read first
- `AGENTS.md` §5.2, §5.7
- `llm.py`, `graph/nodes/*`, `retrieval/rerank.py`, `orders/service.py`, `api/app.py`

## Task
1. `src/support_agent/reliability/`:
   - `timeouts.py` — per-call timeouts from config (rewrite, classify, answer, decide, rerank, Milvus, DB).
   - `retry.py` — retry with exponential backoff + jitter for retryable errors only (timeouts, 429, 5xx); max attempts from config; never retry non-idempotent writes without an idempotency key.
   - `fallback.py` — model fallback chain per role (`main: [primary, secondary]`) from config. Record which model actually answered in state.
   - `circuit.py` — a simple circuit breaker per dependency (closed/open/half-open, counts in Redis or in-process), so a dead dependency fails fast.
2. **Fail-closed rules** (document each in `docs/RELIABILITY.md` as a table: dependency down → behaviour):
   - Reranker down → knowledge and refund paths hand off with reason `dependency_unavailable` (the gate is calibrated on rerank scores).
   - Milvus down → same.
   - Orders DB down → tools/refund paths hand off.
   - Classifier fails → `chitchat_other` fallback reply that offers a human.
   - Answer model fails after fallbacks → handoff.
3. **Structured-output repair** — if structured output fails to parse, one repair attempt with the error message, then the safe default for that node.
4. **Idempotency** — refund requests and handoff creation take an idempotency key (`conversation_id + turn_id + action`); a unique constraint in Postgres (migration). A retried request returns the existing record.
5. **Per-conversation lock** — Redis lock around a graph run for one conversation id; a second concurrent request gets HTTP 409 with a clear message (UI shows "still answering…").
6. **Metrics** — `/metrics` (Prometheus): request count/latency by path and outcome, LLM calls/latency/errors by role and model, retries, fallbacks used, circuit state, handoffs by reason, gate pass rate. Low-cardinality labels only.
7. **Chaos tests** — `tests/chaos/` with fakes that time out, 429, return garbage, or raise; and `make chaos` that runs the smoke eval with a fault-injection config (e.g. 20% LLM timeouts, reranker down for 50% of calls) and writes `eval/reports/chaos.md`: answer rate, handoff reasons, **false-accept must stay 0**.

## Requirements
- All new numbers in config. All fallbacks and handoffs traced with the reason.
- No behaviour change when nothing fails: smoke eval compare → no significant change.

## Tests
- Retry only on retryable errors; backoff bounded; total time ≤ budget.
- Fallback chain used in order; `answered_by_model` recorded.
- Circuit opens after N failures and half-opens after the cool-down.
- Reranker down → knowledge path hands off with `dependency_unavailable`, zero answer-model calls.
- Duplicate refund request with the same key → one DB row.
- Concurrent requests on one conversation → one runs, one gets 409.

## Out of scope
Guardrails (21), load testing (33).

## Done when
- [ ] `eval/reports/chaos.md` shows false-accept = 0 under faults
- [ ] `docs/RELIABILITY.md` failure table complete
- [ ] `make check` green; PROGRESS row 19 updated
- [ ] Interview note `docs/notes/19-reliability.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(reliability): timeouts, retries, model fallback, circuit breakers, fail-closed handoffs, idempotency and metrics
```
