# 33 — Load testing, SLOs, and backpressure

**What**
I defined service level objectives and error budget rules in `docs/SLO.md`.
I built a Locust suite, a timed mock LLM server, and a profiled harness.
I added a short-TTL customer allowlist cache and a bounded in-flight backpressure limiter.
Overflow requests now return HTTP 503 with `Retry-After` instead of timing out.

**Why**
Single-request latency hides concurrency bottlenecks like repeated database lookups and worker saturation.
Without bounded concurrency, traffic spikes pile up until requests time out or crash the process.
A deterministic mock LLM lets us load-test API capacity without paying per-token fees.
Profiling before and after ensures every speed fix is measured and keeps answer quality unchanged.

**Number**
Across 160 weighted requests at concurrency 16, throughput rose from 66.2 to 77.1 req/s.
Overall P95 fell from 346.5 ms to 293.6 ms, and P99 hit 315.7 ms.
Under spike load, backpressure shed 44 requests cleanly with HTTP 503 and zero unhandled errors.
Policy TTFT P95 hit 275.7 ms, missing the 250 ms target.
Source: eval/reports/load.md

**Trade-off**
Policy TTFT equals full-answer latency because `output_guard` buffers the full draft before streaming.
We kept that safety buffer instead of streaming unchecked text to hit 250 ms TTFT.
Capacity tests use a mock LLM, so live latency still depends on DeepSeek and Milvus.
Live latency stays anchored to our real-model reports in `context_ab.md` and `cache.md`.

**Likely follow-up question**
Q: Why return HTTP 503 with `Retry-After` instead of queueing requests inside FastAPI?
A: Unbounded internal queues turn short spikes into long tail latency and cascading timeouts.
Rejecting overflow fast keeps latency healthy for admitted users and protects worker memory.
Clients can back off and retry cleanly using the `Retry-After` header.
