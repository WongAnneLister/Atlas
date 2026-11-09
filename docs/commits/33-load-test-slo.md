# Commit 33 — Load testing, SLOs, and performance work backed by profiles

**Phase 2 · Ops · depends on: 19, 26, 28**

## Context
"Production grade" needs numbers for capacity and latency under load, not just single-request latency. Define SLOs, measure
against them with a load test, find the bottleneck with a profile, fix it, and measure again.

## Read first
- `docs/RELIABILITY.md`, `eval/reports/cache.md`, `eval/reports/context.md`, `/metrics` output

## Task
1. `docs/SLO.md` — SLOs from the v1/phase-2 baselines, e.g.: availability of `/api/chat` (non-5xx) ≥ 99.5% in the load test; P95 time-to-first-token for knowledge answers ≤ X s; P95 full answer ≤ Y s; P95 refund decision ≤ Z s; error budget policy. Choose X/Y/Z **after** a first measurement and justify them.
2. **Load test** — `loadtest/locustfile.py` with weighted user types (policy Q 50%, order status 20%, refund 15%, chit-chat 10%, attack 5%), SSE consumption, order-picker resume, think time. Profiles: steady (N users), ramp, spike. `make loadtest PROFILE=steady USERS=...`.
   Use a **mock LLM server** mode (configurable fixed latency + token rate, deterministic text) for capacity tests so cost stays near zero, plus one short run with real models to validate.
3. Report `eval/reports/load.md`: throughput, P50/P95/P99 per endpoint and per path, error rate, resource use (CPU/mem of API, Milvus, reranker), and which SLOs pass.
4. **Profile, then fix** — profile the hot path (py-spy or cProfile under load). Expected suspects: reranker on CPU (batching, max candidates, ONNX/quantised model, a separate worker), embedding calls, sync DB calls inside async handlers, Milvus search params. Fix the top 1–2 bottlenecks, each as a measured change: before/after load numbers **and** quality unchanged (`eval-compare` on the smoke set — e.g. reducing rerank candidates must not hurt Recall@5 or false-accept).
5. **Concurrency settings** — workers, connection pools, semaphores around model calls (bounded concurrency per provider with backpressure → 429/503 with Retry-After, not timeouts). Document chosen values.

## Requirements
- Every performance change keeps quality (paired compare) — speed bought with accuracy is reported as a trade-off, not a win.
- The mock LLM is never used in quality evals.

## Tests
- Mock LLM server returns deterministic streams with configured timing.
- Backpressure: beyond the concurrency limit, requests get 429/503 with Retry-After.

## Out of scope
Autoscaling infrastructure.

## Done when
- [ ] `docs/SLO.md` and `eval/reports/load.md` with before/after for the fixed bottleneck(s)
- [ ] `make check` green; PROGRESS row 33 updated
- [ ] Interview note `docs/notes/33-load-test-slo.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
perf: SLOs, Locust load tests with mock LLM, profiled bottleneck fixes and backpressure
```
