# Commit 18 — Platform: PostgreSQL, Redis, durable checkpoints, migrations

**Phase 2 · depends on: 17**

## Context
v1 keeps orders in SQLite and graph checkpoints in memory or SQLite. With several API workers, restarts, and interrupts that
may wait minutes for a user (order picker, later human handoff), state must be durable and shared.
This commit moves state to PostgreSQL, adds Redis for locks/cache/rate limits, and introduces migrations.

## Read first
- `AGENTS.md` §2 (phase-2 table), §5.7
- `src/support_agent/orders/`, `graph/build.py`, `api/app.py`, `docker-compose.yml`
- LangGraph Postgres checkpointer docs for the installed version

## Task
1. `docker-compose.yml`: add `postgres` (with a named volume and healthcheck) and `redis`. Keep Milvus. `make up` starts all.
2. `src/support_agent/db/`: SQLAlchemy 2.0 (Core or ORM — pick one and say why in `docs/ARCHITECTURE.md`), async engine, session helpers. Alembic set up under `migrations/`; `make migrate`.
3. Port the order schema to Postgres via a migration. `OrderService` keeps the same public interface; add a repository implementation for Postgres. SQLite stays as the default for **unit tests only**.
   `make data-orders` seeds Postgres.
4. Graph checkpoints → LangGraph Postgres checkpointer (config switch: `memory | sqlite | postgres`; default `postgres` when `ENV=prod|dev`, `memory` in tests).
5. Redis client wrapper in `src/support_agent/infra/redis.py` with a `NullRedis` for tests. (Locks, caches and rate limits that use it come in 19/21/26.)
6. Config per environment: `configs/default.yaml` + `configs/dev.yaml` + `configs/prod.yaml`, chosen by `ENV`. Secrets only from env.
7. Readiness vs liveness: `/api/health/live` (process up) and `/api/health/ready` (Postgres, Redis, Milvus, migrations at head).
8. `docs/ARCHITECTURE.md` (create): a component diagram (Mermaid) of API, graph, Milvus, Postgres, Redis, Langfuse; what state lives where and why.

## Requirements
- Interrupts survive an API restart: start a refund, get the order picker, restart the API, resume → it continues.
- No business logic change: run `make eval-e2e` on the smoke set and `make eval-compare` vs baseline → `no significant change`.

## Tests
- Repository contract tests run against SQLite in unit tests and against Postgres under `@pytest.mark.integration`.
- Migration up/down on an empty DB (integration).
- Readiness reports each dependency separately.
- Integration test: interrupt → new graph instance (simulated restart) → resume works.

## Out of scope
Retries/timeouts (19), caching (26).

## Done when
- [ ] Restart-resume scenario demonstrated (integration test + manual note)
- [ ] Eval compare vs baseline: no significant change (paste verdict in PROGRESS)
- [ ] `make check` green; PROGRESS row 18 updated
- [ ] Interview note `docs/notes/18-postgres-redis.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(platform): PostgreSQL with Alembic, Redis, durable LangGraph checkpoints and readiness checks
```
