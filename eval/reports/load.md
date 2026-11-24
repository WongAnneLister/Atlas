# Load Test & Performance Report (Commit 33)

## Provenance
- Date: `2026-11-24 02:44 UTC`
- Git SHA: `8fc01a5`
- Workload: weighted mix (50% policy Q, 20% order status, 15% refund, 10% chitchat, 5% attack), concurrency=`16`, mock LLM base latency=`15 ms` (capacity test only; never used in quality evals).
- Live model validation: validated against live DeepSeek + local Milvus baseline in `eval/reports/context_ab.md` (P50 4.29 s / P95 14.53 s) and `eval/reports/cache.md` (mean 13.60 s -> 1.98 s warm).

## Before vs After Bottleneck Fix (Customer Allowlist TTL Cache + Bounded Backpressure)

| Metric | Before (`customer_cache_ttl_s=0`) | After (`customer_cache_ttl_s=30`, `max_in_flight=32`) | Spike Backpressure (`max_in_flight=4`, conc=16) |
|---|---:|---:|---:|
| Total requests | 160 | 160 | 48 |
| 2xx success (availability) | 160/160 (100.00%) | 160/160 (100.00%) | 4/48 |
| Backpressure 503 (`Retry-After`) | 0 | 0 | 44 |
| Unhandled 5xx / other errors | 0 | 0 | 0 |
| Throughput (req/s) | 66.2 | 77.1 | 272.7 |
| Overall P50 / P95 / P99 (ms) | 229.7 / 346.5 / 404.8 | 205.6 / 293.6 / 315.7 | — |
| Peak API RSS memory (MB) | 170.4 | 185.5 | 185.5 |

## Per-Path Latency (After Fix, Mock LLM)

| Path | Count | TTFT P95 (ms) | Full P50 (ms) | Full P95 (ms) | Full P99 (ms) |
|---|---:|---:|---:|---:|---:|
| `attack` | 7 | 111.4 | 70.5 | 111.4 | 111.4 |
| `chitchat` | 17 | 315.7 | 214.7 | 315.7 | 315.7 |
| `order_status` | 29 | 273.6 | 207.6 | 273.6 | 276.6 |
| `policy_question` | 83 | 275.7 | 202.8 | 275.7 | 306.5 |
| `refund_request` | 24 | 303.6 | 217.8 | 303.6 | 316.3 |

## SLO Verification (Capacity Harness)

| SLO | Target | Measured (After) | Status |
|---|---|---:|---|
| `/api/chat` availability (non-5xx) | >= 99.5% | 100.00% | PASS |
| Policy Q TTFT P95 (mock LLM) | <= 250 ms | 275.7 ms | FAIL |
| Policy Q full answer P95 (mock LLM) | <= 500 ms | 275.7 ms | PASS |
| Refund flow P95 (mock LLM) | <= 600 ms | 303.6 ms | PASS |
| Spike backpressure sheds cleanly (503 + Retry-After, 0 crashes) | > 0 shed, 0 unhandled | 44 shed, 0 err | PASS |

## Quality Preservation
- `CustomerAllowlistCache` and `InFlightLimiter` do not alter retrieval candidates, reranking, prompt layout, or gate thresholds; retrieval Recall@5 (`1.0000`) and no-answer false-accept (`0/30`) from the promoted baseline are unchanged.

## Top cProfile Hotspots (After Fix)
```text
     2346    0.007    0.000    1.386    0.001 /Library/Frameworks/Python.framework/Versions/3.11/lib/python3.11/selectors.py:553(select)
     2346    1.378    0.001    1.378    0.001 {method 'control' of 'select.kqueue' objects}
11985/10552    0.013    0.000    0.657    0.000 {method 'run' of '_contextvars.Context' objects}
     2384    0.003    0.000    0.394    0.000 /Users/anne_lister/proj/Atlas/loadtest/run_load.py:268(one_req)
     2240    0.001    0.000    0.366    0.000 /Library/Frameworks/Python.framework/Versions/3.11/lib/python3.11/contextlib.py:199(__aenter__)
     2400    0.001    0.000    0.365    0.000 /Users/anne_lister/proj/Atlas/.venv/lib/python3.11/site-packages/httpx/_client.py:1542(stream)
     2240    0.001    0.000    0.331    0.000 /Users/anne_lister/proj/Atlas/.venv/lib/python3.11/site-packages/httpx/_client.py:1594(send)
     2240    0.001    0.000    0.329    0.000 /Users/anne_lister/proj/Atlas/.venv/lib/python3.11/site-packages/httpx/_client.py:1645(_send_handling_auth)
```
