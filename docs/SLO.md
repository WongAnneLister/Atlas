# Service Level Objectives & Capacity Settings (`docs/SLO.md`)

SLOs are grounded in two measured baselines:
1. **API / orchestration capacity harness** (`eval/reports/load.md`, weighted 50/20/15/10/5 traffic mix, concurrency 16, deterministic 15 ms mock LLM — isolates API, DB, SSE, and LangGraph overhead).
2. **Live model + Milvus + MPS reranker baselines** (`eval/reports/context_ab.md`, `eval/reports/cache.md`, `eval/reports/e2e.md`).

## 1. SLO Targets

| SLI | Production Target (Live LLM) | Capacity Harness Target (Mock LLM) | Basis |
|---|---|---|---|
| `/api/chat` availability (non-5xx) | `>= 99.5%` | `>= 99.5%` | Measured `100.00%` (160/160) in `eval/reports/load.md` |
| Knowledge answer TTFT P95 | `<= 16.0 s` | `<= 250 ms` | `output_guard` buffers drafts before SSE release so TTFT ≈ full latency; capacity harness measured `275.7 ms` (FAIL — documented trade-off for output safety) |
| Knowledge full answer P95 | `<= 18.0 s` | `<= 500 ms` | Live `chunked` P95 `14.53 s` (`eval/reports/context_ab.md`), warm cache mean `1.98 s` (`eval/reports/cache.md`); capacity harness `275.7 ms` (PASS) |
| Refund decision P95 | `<= 20.0 s` | `<= 600 ms` | Includes order lookup + policy retrieval + decision check; capacity harness `303.6 ms` (PASS) |
| Safety invariant (no-answer false accept) | `0%` | `0%` | Non-negotiable release gate (`eval/gate_rules.yaml`) |

## 2. Error Budget Policy

- **Monthly error budget** at `99.5%` availability: `0.5%` of `/api/chat` requests (~216 minutes/month equivalent).
- **Burn-rate triggers**:
  - `> 25%` of monthly budget burned in 24 h → freeze non-reliability feature merges; inspect `atlas_requests_total{outcome="error"}` and `atlas_circuit_state`.
  - `> 50%` burned in 7 d → require load/chaos replay before next release.
  - Any `0%` safety invariant breach (`no_answer` false accept > 0) → immediate release block regardless of availability budget.
- **Backpressure vs 5xx**: Clean load shedding (`503 Service Unavailable` with `Retry-After`) protects the process from timeout cascades and OOMs when `max_in_flight` is exceeded. Clients retry after `Retry-After` seconds rather than piling onto saturated workers.

## 3. Concurrency, Pools & Backpressure Settings (`configs/default.yaml`)

| Setting | Value | Purpose |
|---|---:|---|
| `api.concurrency.max_in_flight` | `32` | Bounds concurrent `/api/chat` + `/api/resume` turns per worker; overflow returns HTTP `503` + `Retry-After` |
| `api.concurrency.retry_after_s` | `2` | `Retry-After` header returned when `max_in_flight` is saturated |
| `api.concurrency.customer_cache_ttl_s` | `30.0` | Caches demo customer allowlist in memory to remove a sync DB query from every `/api/chat` turn |
| `reliability.llm_max_in_flight` | `16` | Bounds concurrent outbound LLM calls per process via `BoundedExecutor` |
| `api.rate_limit.per_customer` / `per_ip` | `30` / `120` per 60 s | Per-principal fixed-window rate limits (HTTP `429` + `Retry-After`) |
| `db.pool_size` / `max_overflow` | `5` / `0` | Bounded Postgres connection pool with `pool_pre_ping: true` |

## 4. Measured Bottleneck Fix

Profiling the hot `/api/chat` path revealed a synchronous `orders.list_customers()` query on every turn before acquiring a conversation lock, plus unbounded in-flight turn concurrency under spikes.
- Adding `CustomerAllowlistCache` (`ttl_s=30`) raised steady throughput from `66.2 req/s` to `77.1 req/s` (+16.5%) and cut overall P95 latency from `346.5 ms` to `293.6 ms` (P99 `404.8 ms` → `315.7 ms`) with zero quality impact (`eval/reports/load.md`).
- Adding `InFlightLimiter` cleanly shed `44/48` overflow requests with HTTP `503` + `Retry-After: 2` and `0` unhandled errors during the spike test (`max_in_flight=4`, concurrency `16`).
