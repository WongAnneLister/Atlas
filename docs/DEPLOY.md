# Public Demo Deployment (`docs/DEPLOY.md`)

## 1. Deployment Target & Justification

We target a **single Linux VM (4 vCPU, 8 GB RAM, 40 GB SSD, ~$20–$30/mo)** running `docker-compose.prod.yml` + **Caddy** for automatic Let's Encrypt HTTPS.

Why this setup over a multi-service PaaS + managed vector DB:
- **Low fixed cost**: One VM hosts Caddy, the FastAPI API, PostgreSQL, Redis, and Milvus standalone with zero per-service networking fees.
- **Persistent volumes**: Named Docker volumes keep Postgres data, Redis AOF, Milvus index segments, Caddy TLS certificates, and cached BGE-M3 / reranker weights (`model_cache`) across restarts.
- **Zero-config HTTPS & SSE**: `deploy/Caddyfile` obtains and renews TLS certificates automatically and sets `flush_interval -1` so Server-Sent Events stream without proxy buffering.
- **Secrets via env only**: `Dockerfile` bakes zero credentials; all keys come from `.env` on the host.

## 2. Public Demo Guardrails & Cost Caps

- **Daily LLM spend cap**: Set `DEMO_DAILY_SPEND_CAP_USD=5.0` (tracked in `src/support_agent/api/budget.py` with UTC midnight rollover). Once reached, new `/api/chat` turns return a friendly `demo_budget_reached` handoff without calling any LLM.
- **Rate limits & backpressure**: Fixed-window per-customer (`30/min`) and per-IP (`120/min`) rate limits plus bounded concurrency (`max_in_flight=32`, overflow returns HTTP `503` + `Retry-After: 2`).
- **Demo customers only**: `/api/session` issues signed Bearer tokens only for seeded synthetic customers (`example.com`).
- **Demo banner**: The chat page displays a persistent banner stating all data is synthetic.

## 3. First-Time Provisioning

```bash
# 1. On the VM, clone the repo and copy .env.example -> .env
cp .env.example .env
# Fill in: LLM_PROVIDER, LLM_FAST_MODEL, LLM_MAIN_MODEL, DEEPSEEK_API_KEY,
# SESSION_SECRET, AGENT_TOKEN, ATLAS_POSTGRES_PASSWORD, MINIO_ROOT_PASSWORD,
# ATLAS_DOMAIN, DEMO_DAILY_SPEND_CAP_USD=5.0

# 2. Start the stack with automatic HTTPS
docker compose -f docker-compose.prod.yml up -d --build

# 3. Run Alembic migrations and LangGraph checkpoint setup
docker compose -f docker-compose.prod.yml exec api uv run python -m support_agent.db.migrate

# 4. Verify live & ready probes over HTTPS
curl -fsS "https://${ATLAS_DOMAIN}/api/health/live"
curl -fsS "https://${ATLAS_DOMAIN}/api/health/ready"
```
