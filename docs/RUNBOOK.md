# Operations Runbook (`docs/RUNBOOK.md`)

## 1. Dashboards & Health Endpoints

- **Liveness**: `GET /api/health/live` — process up.
- **Readiness**: `GET /api/health/ready` — checks Postgres, Alembic + checkpoint migrations at head, Redis, and Milvus.
- **Prometheus metrics**: `GET /metrics`
  - Availability & latency: `atlas_requests_total`, `atlas_request_seconds`
  - Reliability: `atlas_circuit_state`, `atlas_retries_total`, `atlas_fallbacks_total`, `atlas_handoffs_total`
  - Cache & context: `atlas_cache_requests_total`, `atlas_context_tokens_total`, `atlas_context_cache_hit_ratio`, `atlas_context_overflows_total`
  - Online eval & drift: `atlas_feedback_total`, `atlas_online_citation_valid_total`, `atlas_drift_metric`
- **Traces**: Langfuse UI (when `TRACING__ENABLED=true`), searchable by `trace_id` from logs and handoff payloads.

## 2. Alert & Drift Breach Playbook

| Alert / Breach | First Check | Action |
|---|---|---|
| `atlas_circuit_state{dependency="..."} == 2` (open) | Check dependency logs (`milvus`, `reranker`, `llm:*`) | Confirm fail-closed handoffs (`dependency_unavailable`); restore dependency; circuit auto-probes after `cool_down_s` |
| `503` spike (`Retry-After`) | Check `atlas_requests_total{outcome="unavailable"}` and CPU/RSS | Inspect traffic spike or slow upstream LLM; increase workers or lower `demo_budget` if abusive |
| `atlas_drift_metric{metric="gate_score_ks"} >= 0.15` or `low_evidence` handoff spike | Open `/console` and run `make loop-report` | Inspect `eval/reports/doc_gaps.md`; add missing policy sections and release via `make index-release` |
| `atlas_drift_metric{metric="thumbs_down_delta"} >= 0.10` | Check `/api/agent/reviews?status=pending` | Review stratified near-threshold sample; never lower `gate.threshold` without `make sweep` on `dev` |
| `demo_budget_reached` handoffs | Check `DEMO_DAILY_SPEND_CAP_USD` and provider dashboard | Confirm expected demo traffic; cap resets automatically at 00:00 UTC |

## 3. Rollbacks

- **Application**: `ATLAS_IMAGE=support-agent:<prev-tag> docker compose -f docker-compose.prod.yml up -d --no-deps api`
- **Milvus index**: `make index-rollback`
- **Database schema**: `uv run alembic downgrade -1` (only after verifying backwards compatibility)

## 4. Key & Secret Rotation

1. **`SESSION_SECRET`**: Set new high-entropy value in `.env` and restart `api` (`docker compose -f docker-compose.prod.yml up -d --no-deps api`). Existing browser tabs automatically re-issue a fresh demo session on 401.
2. **`AGENT_TOKEN`**: Update in `.env`, restart `api`, and distribute the new token to console operators.
3. **LLM API keys (`DEEPSEEK_API_KEY` / `OPENAI_API_KEY`)**: Rotate at the provider, update `.env`, restart `api`, and verify `/api/health`.

## 5. Customer Data Purge (GDPR / Right to Erasure)

1. **Long-term memories**: Customer calls `DELETE /api/me/memories` (or operator runs `CustomerMemoryStore.soft_delete_all(customer_id)`), immediately removing all active memories from future sessions.
2. **Conversation checkpoints & telemetry**: Delete rows scoped to `customer_id` / `thread_id LIKE '<customer_id>:%'` from `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `turn_feedback`, and `online_turn_events` in PostgreSQL.
3. **Verify**: Confirm `GET /api/me/memories` returns `[]` and a fresh session loads `customer_profile = None`.
