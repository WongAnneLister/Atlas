# Reliability

Each worker runs the same synchronous graph. Knowledge and refund answers still use
the evidence gate and its reranked results. A provider retry, fallback model, or
structured-output repair runs inside the existing node.

## Dependency failures

| Dependency | Detection | Behaviour | Handoff reason | Regression test |
|---|---|---|---|---|
| Milvus | Search deadline, connection failure, retryable service response, or open circuit | Discard retrieval results. Knowledge evaluates the gate with empty evidence. Refund stops before deciding. | `dependency_unavailable` | `test_knowledge_never_answers_after_search_or_rerank_failure` |
| Reranker | Deadline, retryable failure, or open circuit | Discard candidates. Knowledge evaluates the gate with empty evidence. Refund stops before deciding. | `dependency_unavailable` | `test_knowledge_never_answers_after_search_or_rerank_failure` |
| Orders DB | Deadline, unavailable connection, or open circuit | Stop lookup or refund processing. The API returns HTTP 503 when it cannot check customer existence. | `dependency_unavailable` | `test_orders_outage_hands_off_on_both_routes` |
| Classifier | Transport failure after the model chain, or invalid structured output after repair | Take the fixed route and offer human help. | Fixed reply | `test_classifier_failures_route_to_fixed_without_logging_raw_text` |
| Knowledge answer model | Transport failure after the model chain | Stop generation. | `dependency_unavailable` | `test_generation_connection_error_does_not_claim_low_evidence` |
| Knowledge answer output | Invalid structured result after repair | Stop generation. A valid repair still goes through coverage and citation checks. | `invalid_answer` | `test_answer_repair_still_checks_citations_and_quotes` |
| Refund decision model | Transport failure after the model chain, or invalid result after repair | Hand off once. A valid repair still goes through the return-window check. | `dependency_unavailable` for a transport failure, `policy_requires_human` for invalid output | See the refund decision tests. |
| Redis turn lease | Lease already held, or Redis operation failed | HTTP 409 for a held lease and HTTP 503 for an unavailable store. Both stop before the graph begins. | HTTP error | `test_chat_and_resume_refuse_to_run_when_lock_store_is_down` |

Unexpected retrieval, answer and tool errors keep their existing handoff reasons.
The gate receives no partial results when either required retrieval stage fails.

## Deadlines and recovery

Site-specific model timeouts, retry budgets, cooldowns and leases live in
`configs/default.yaml`. The model clients use the configured transport timeout
and Atlas also bounds how long a caller waits. The retry layer caps attempts and
uses exponential backoff with jitter. A write can be retried when the caller
supplies the same idempotency key. Model SDK retries are set to zero. The Milvus
SDK can retry internally within an RPC call. Atlas bounds the caller's wait and
counts each outer call as one attempt.

Model fallback lists are empty by default. Configure them by role in YAML or
with `LLM_FAST_FALLBACKS` and `LLM_MAIN_FALLBACKS`. Transport failures can advance
the model chain. Structured output gets one same-model repair call with a short
validation summary. These calls record model names, attempts, and failure types
in the graph state.

Circuits are in process. Each worker learns independently. The check happens without a network hop. An open circuit rejects the dependency immediately. A
recovery probe can run after cooldown. The breaker counts whole calls, not retry
attempts: a call whose retries all fail counts as one failure, so one unlucky call
cannot open the circuit for every later request (seen in the first 19a smoke run). The reranker has a dedicated single
worker and no growing queue. A timed-out Python call can still be running
because Python cannot stop an in-process inference thread. The worker remains
occupied until that call finishes.

## Writes and streaming

The persisted conversation and message IDs, together with the action, determine
the key for a refund write. PostgreSQL and SQLite enforce uniqueness. An exact
replay returns the saved request. A conflicting replay fails and goes to human
review. Handoff state also carries a stable key. Commit 31 adds its uniqueness
constraint when it introduces the handoff queue. A guarded write passes its
deadline into the transaction. A deadline that expires before commit rolls
back the write. If the database accepts a commit before a lost response,
replaying the same key returns the saved request.

Chat and resume share a conversation lease. The server refreshes the lease every
`renew_interval_s` during streaming, so the TTL stays short (60 s by default) and only
bounds how long a crashed holder blocks its conversation. The server closes the
stream if renewal fails. Refresh and release both check the owner
token. Release runs when SSE closes. Expiry lets another worker recover after a
crashed holder. Local mode uses the same lease operations in process.

## Metrics and trace IDs

`GET /metrics` exposes request totals and durations, model attempts and
durations, retries, fallbacks, repairs, circuit state, handoffs, gate outcomes
and graph paths. Stream errors count as failed requests even after HTTP headers
have been sent. Labels contain fixed categories and configured model names.
Each API request gets a trace ID for logs, optional Langfuse traces and handoff
payloads. OpenMetrics can carry the ID in an exemplar without creating a time
series per request. Several API workers will need Prometheus multiprocess
collection through `PROMETHEUS_MULTIPROC_DIR`.
[Prometheus exemplar documentation](https://prometheus.github.io/client_python/instrumenting/exemplars/)

## Fault evaluation

`make chaos` runs the frozen smoke questions with a seeded fault configuration
and writes `eval/reports/chaos.md`. A repeated seed gives the same decisions
for the same sequence of calls. Live provider responses can change that
sequence. The injector raises timeout and rate-limit errors without waiting for
a real outage. The evaluation reports false accepts with uncertainty bounds and
stops on any observed no-answer false accept. Chaos records have their own
run kind, so release comparison and baseline promotion reject them.
