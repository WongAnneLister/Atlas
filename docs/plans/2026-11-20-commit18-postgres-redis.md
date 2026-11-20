# Commit 18 execution plan — PostgreSQL, Redis, durable checkpoints, readiness

Read this together with `docs/commits/18-postgres-redis.md` (the task) and `AGENTS.md` (the rules).
This plan does not change the goal of the task. It fixes the places where the task prompt does not match the
repository as of 2026-11-20 (`main` = `d066d24`), and it orders the work.
If this plan and `AGENTS.md` disagree, follow `AGENTS.md` and say so.

## 0. Preconditions (check first; stop and report if one fails)

1. **Branch.** Start from `main` at `d066d24` or later. Work on `codex/c18-postgres-redis`. Do not push.
2. `make check` is green before you change anything.
3. **Docker.** The Docker CLI is installed, but the daemon was not running on 2026-11-20.
   The author starts Docker Desktop. If `docker info` still fails, write all offline code and tests,
   then stop before the integration and eval steps (§5.2–5.5) and report what is left.
4. **Milvus** runs on a VPS. It is reached through an SSH tunnel on `localhost:19530`. It is not in local Docker.
   You need it only for the smoke eval in §5.4. If the tunnel is down, ask the author to reopen it.
5. **LLM.** Eval targets need `.env` loaded: `set -a; source .env; set +a`.
6. **Port 5432 is taken** on the author's machine (checked 2026-11-20): a native Postgres listens on
   `127.0.0.1:5432`, and another project's container (`dispatch-database-1`) publishes `0.0.0.0:5432`.
   Port 6379 is free; that project's Redis uses 6380. Do not stop or reuse those services.
   Atlas's Postgres must use another host port (§2.8). A URL pointing at `localhost:5432` would silently reach
   the wrong database. Migrations and seeding would then write into another project's server.

## 1. Facts about the repository that change the task

| Task prompt says | Reality | What to do instead |
|---|---|---|
| SQLAlchemy **async** engine | The graph is synchronous. `api/runner.py` runs `graph.stream` in a thread pool, and `OrderService` and every node are sync. | Use the **sync** SQLAlchemy 2.0 engine with psycopg 3. Use the sync `PostgresSaver`. Going async would rewrite every node, which is a business-logic change the task forbids. Write the reason in `docs/ARCHITECTURE.md`. |
| "Default `postgres` when ENV=prod\|dev, `memory` in tests" | `AGENTS.md` §5.4 says the app must start with only `LLM_*` set. | Add a third value: `ENV` unset means `local`. `local` uses SQLite orders, memory checkpoints and `NullRedis`, so §5.4 still holds. `dev` and `prod` use Postgres and Redis. Tests force `local`. |
| SQLite only for unit tests | Every eval script and `make serve` read `data/orders.sqlite`, and `eval/orders_seed.py` audits it (`ORDER BY rowid`). | SQLite stays the `local` backend. Do not delete it. Keep `make eval-orders` working on SQLite, and keep its committed outputs byte-identical. |
| `make eval-e2e` on smoke, then `make eval-compare` vs baseline | Commit 17 built `make eval-smoke` and `make eval-gate` against `eval/baselines/main.json`. | Run `make eval-smoke` under `ENV=dev`, then `make eval-gate RUN=…`. Paste the gate verdict into PROGRESS. |
| The smoke compare proves "no business change" | The smoke set holds only knowledge questions (5 groups, no order questions). It barely touches orders. | Add a deterministic **order parity check** (§4.3). Seed SQLite and Postgres from the same seed and compare every table. This is the real proof for orders. |
| Durable checkpoints | `eval/e2e_eval.py` uses `thread_id = f"e2e:{split}:{item.id}"`, and grounding and order-replies evals use fixed ids too. With a durable store, a second run would **resume the first run's conversation**. | Put the run id (or a fresh nonce) into every eval thread id. Add a test that two runs never share a thread id. |
| `make up` starts everything | Milvus is on the VPS, and a local Milvus is heavy. | `make up` still starts all services, as the prompt asks. Add `make up-state` that starts only `postgres` and `redis`. |
| — | `src/support_agent/config.py` is already 423 lines. | Put new settings models in their modules (`db/settings.py`, `infra/settings.py`) and import them into `Settings`. Do not grow `config.py` by more than ~30 lines. |
| — | The config hash covers all of `Settings`. `make data-validate-docs` compares it with the hash stored when the docs were built. | New sections change the hash. `data-validate-docs` may then say "Build config changed". This was already true for every config change. Do **not** rebuild docs here. Record it in PROGRESS known issues and propose a follow-up that hashes only the build-relevant sections. |
| `/api/health/live` and `/ready` | `/api/health` already exists, and offline tests cover it. | Keep `/api/health` unchanged. Add the two new routes next to it. |

## 2. Design (fixed here so the work does not drift)

### 2.1 Environments and config layering
- `ENV` ∈ {`local` (default when unset), `dev`, `prod`}. Read it once in `config.py`.
- Base YAML = `SUPPORT_AGENT_CONFIG` or `configs/default.yaml`. Overlay = `configs/{ENV}.yaml` when ENV is dev or prod.
  Merge with an explicit, tested **deep merge** (dicts merge recursively; lists and scalars replace).
  Do not rely on pydantic-settings' merge of a `yaml_file` list. Check what 2.16.2 does; if you are unsure, write your own.
- `configs/dev.yaml` and `configs/prod.yaml` hold only the keys that differ: backends and pool sizes. They hold no secrets.
- Secrets and addresses only from env: `DATABASE_URL`, `REDIS_URL`. Add both, plus `ENV`, to `.env.example` with
  local-only example values (`postgresql+psycopg://support:support@localhost:5433/support`, `redis://localhost:6379/0`).
  The port 5433 matches the compose default in §2.8, not the Postgres default.
- `prod` refuses to start when any of these hold: the checkpoint backend is not `postgres`, `DATABASE_URL` is unset,
  or Redis is `null`. It fails with a clear message at settings load.
- Add the tests (pure, offline): overlay wins, deep merge keeps sibling keys, unset ENV means local, and prod rejects memory checkpoints.

### 2.2 Database layer — `src/support_agent/db/`
- Choose SQLAlchemy **Core**, not ORM. Write the reason in ARCHITECTURE: the repository already maps rows to Pydantic
  domain models, ORM classes would duplicate them, and Core gives one table definition for both SQLite and Postgres.
- `db/engine.py`: `make_engine(url, settings)` uses pool size, timeouts and `pool_pre_ping` from config.
  It has one `transaction(engine)` context manager (`engine.begin()`). Callers own the engine and dispose it on close.
- `src/support_agent/orders/tables.py`: one Core `MetaData` with the seven order tables.
  Carry over every constraint in `orders/schema.sql`: CHECKs (including `email LIKE '%@example.com'`),
  composite FKs, UNIQUEs and the `orders_customer_date` index.
  Use real types: BIGINT cents, BOOLEAN flags, and DATE/TIMESTAMPTZ where the model is a date or datetime.
- **One** repository: `orders/sql_repository.py` implements the current `OrderRepository` interface on a SQLAlchemy
  engine. It works on both SQLite and Postgres, so the contract tests test the same code on both.
  `OrderService` keeps its public interface. It picks the engine from settings. The `db_path` parameter still works for tests.
- The old sqlite3 `orders/db.py` may stay as a thin alias for `eval/orders_seed.py` only if keeping it is simpler.
  Either way, `make eval-orders` must produce byte-identical committed outputs. Diff them before and after.
- Do not change refund semantics. The `REF-<uuid>` id and `pending_review` status stay as they are.
  Idempotency keys come in commit 19.

### 2.3 Migrations — `migrations/` (Alembic)
- `alembic.ini` at the repo root. `migrations/env.py` takes the URL from settings and the target metadata from `orders/tables.py`.
- `include_object` excludes LangGraph's checkpoint tables (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`,
  `checkpoint_migrations`). Without it, autogenerate would try to drop them.
- Revision `0001_orders` creates the order tables. Its `downgrade()` drops them.
- `make migrate` = `alembic upgrade head` + `PostgresSaver.setup()`. Both steps are idempotent.
  The API never runs DDL at startup. Readiness reports a missing migration instead.
- SQLite (`local`) creates tables with `metadata.create_all` inside the seed, like today's `schema.sql` reset.

### 2.4 Seeding
- `make data-orders` seeds the backend that the current ENV selects. Under `local` it writes SQLite, as today.
  Under `dev` it seeds Postgres, and it needs `make migrate` first.
- Keep the reset-and-insert in one transaction. Keep `seed_metadata`.
  Postgres has no `rowid`, so any ordering that relied on it uses primary keys.

### 2.5 Checkpointer
- `graph.checkpoint_backend: Literal["memory", "sqlite", "postgres"]`.
- Add the dependency `langgraph-checkpoint-postgres` and `psycopg[binary,pool]` as a `postgres` extra
  (like the `sqlite` extra), and lock it with uv. Check the import path and constructor in the installed version.
- `GraphDeps.checkpointer()` opens a `psycopg_pool.ConnectionPool` with `autocommit=True`, `prepare_threshold=0` and
  `row_factory=dict_row`. It registers the pool on `_resources`, so `GraphDeps.close()` closes it. It never calls `setup()`.
- `api/runner.py` already streams with `durability="sync"`. Keep that.
- **Serialization trap.** `ConversationState` holds Pydantic models (gate result, retrieval snapshot, orders).
  Prove that a real state round-trips through Postgres. Watch for LangGraph's warnings about deserializing
  unregistered types. If the installed version needs an allowlist, configure the serializer explicitly and
  test that path. Never fall back to pickle.

### 2.6 Redis — `src/support_agent/infra/redis.py`
- A small `KeyValueStore` Protocol has `ping`, `get`, `set(key, value, ttl_s)`, `delete`, `incr(key, ttl_s)` and
  `set_if_absent(key, value, ttl_s)`. Commits 19 (locks), 21 (rate limits) and 26 (cache) need these.
- `RedisStore` uses sync `redis-py` with timeouts from config. `NullRedis` is in-memory with TTL, uses an injected clock, and is used in `local` and in tests.
- Nothing calls Redis yet except readiness. Do not move the API's in-process turn locks to Redis; that is commit 19.

### 2.7 Health
- `GET /api/health/live` returns 200 `{"status": "ok"}`. It touches no dependency.
- `GET /api/health/ready` runs each check in a thread with its own timeout from config, all checks concurrently.
  It reports each one separately: `postgres`, `migrations` (Alembic at head **and** checkpoint tables present),
  `redis` and `milvus`, each with the value `ok | down | disabled`.
  A dependency the current ENV does not use is `disabled`, not `down`. The status is 200 when every enabled check is `ok`, and 503 otherwise.
- The body carries no error text or connection string. It gives only the check name and state. Log the exception type.

### 2.8 Compose
- Add `postgres:16-alpine` (pin a minor tag). It gets the named volume `postgres_data` and a `pg_isready` healthcheck.
  Publish it on `127.0.0.1:${ATLAS_POSTGRES_PORT:-5433}:5432`, because 5432 is taken on the author's machine (§0.6).
- Add `redis:7-alpine` (pin a minor tag). It gets a `redis-cli ping` healthcheck.
  Publish it on `127.0.0.1:${ATLAS_REDIS_PORT:-6379}:6379`. Locks and cache need no persistence.
- Add both port variables to `.env.example`. The compose test checks that the defaults agree with the example URLs.
- `make migrate` and `make data-orders` print the target host, port and database name (never the password) before writing.
  They refuse a database that holds tables neither in our metadata nor in LangGraph's checkpoint set.
  This guards against writing into another project's server.
- Use local-dev credentials only. Read them from env with defaults, like Langfuse's local values. Do not collide with `langfuse-postgres`.
- Extend `tests/test_compose.py` to cover the new services, their healthchecks and the loopback-only ports.

### 2.9 Docs
- Create `docs/ARCHITECTURE.md`. It holds a Mermaid component diagram of the API, graph, Milvus (VPS), Postgres, Redis and Langfuse.
  It has a "what state lives where and why" table, and it names the ENV matrix (local/dev/prod → backends).
  It records the Core vs ORM and sync vs async decisions.

## 3. Order of work (each step ends with `make check` green)

1. Config layering + `ENV` + the dev/prod YAML files + tests.
2. Compose services + `make up-state` + compose tests.
3. `db/` + `orders/tables.py` + the SQLAlchemy repository. Switch `OrderService` to it. Contract tests on SQLite.
   Diff the `make eval-orders` outputs before and after; they must be identical.
4. Alembic + `make migrate` + the migration tests (integration).
5. Postgres seeding + the parity check (§4.3).
6. Checkpointer switch + unique eval thread ids + the restart-resume test (integration).
7. Redis wrapper + `NullRedis` tests.
8. `/api/health/live` and `/api/health/ready` + tests.
9. `docs/ARCHITECTURE.md`.
10. Verification (§5), PROGRESS, interview note, one commit.

## 4. Tests

### 4.1 Offline (`make check`)
- Repository contract suite, written once as a parametrised fixture `order_repository(backend)`.
  It runs on SQLite offline and on Postgres under `@pytest.mark.integration`.
  Cover every public method, ownership checks (wrong customer → `OrderNotFound`), invalid refund requests,
  Decimal money round-trip, and date/datetime round-trip. Assert equal Pydantic models, not equal rows.
- Config: deep merge, ENV selection, prod guard.
- Checkpointer factory: `memory` and `sqlite` return the right saver. `postgres` without a URL fails with a clear error.
- Eval thread ids include the run id.
- `NullRedis`: TTL expiry with a fake clock, `set_if_absent` and `incr`.
- Readiness with fake checks: all ok → 200; one down → 503 with that name `down` and the others still reported;
  a slow check → `down` after its timeout; unused dependency → `disabled`. `/live` never calls a check.
- Existing graph tests still assert the same node sequences.

### 4.2 Integration (`pytest -m integration`, needs `make up-state`)
- The repository contract suite on Postgres.
- Migrations: empty DB → `upgrade head` → `downgrade base` → `upgrade head`. Assert that the table set matches the metadata,
  and that autogenerate on a migrated DB reports no diff. That check catches the checkpoint-table drop trap.
- Restart-resume: Postgres checkpointer, refund request for a customer with several orders → `order_picker` interrupt.
  Then close `GraphDeps`, build **new** `GraphDeps` and a **new** graph (a simulated restart), and resume with `Command(resume=…)`.
  Assert that the route continues `refund_load → refund_retrieve → …`, and that state from before the restart is present.
  Use fake models and an in-memory retriever, so only the checkpointer is real.
- Readiness against the real Postgres and Redis.

### 4.3 Order parity check (deterministic, no LLM)
- Script `eval/orders_parity.py` + `make eval-orders-parity`. It seeds a temp SQLite file and a fresh Postgres database
  from the same seed. It reads every order for every customer through `OrderService` on both, and compares the
  Pydantic models. Write `eval/reports/orders_parity.md` with counts and mismatches. The expected result is 0 mismatches.
  The report records the git SHA, config hash and date (`AGENTS.md` §5.1).

## 5. Verification and evidence

1. `make check` green.
2. `make up-state && make migrate && pytest -m integration -k "orders or migration or checkpoint or ready"` green.
3. `make eval-orders-parity` → 0 mismatches; the report is committed.
4. Smoke eval on the new platform: `ENV=dev`, `make data-orders`, `make eval-smoke`, then `make eval-gate RUN=<run dir>`.
   Paste the verdict lines into PROGRESS row 18. Expect "Passed" with no significant change. If a metric moves,
   report the real result and the dependency-error count (§5.1: do not hide it, do not re-run until it passes).
   Note that latency is report-only. Commit the run's `manifest.json` and `metrics.json` (not `items.jsonl`).
5. Manual restart demo. `ENV=dev make serve`, then `POST /api/chat` with a refund request for a multi-order customer,
   which returns the picker. Stop the server and start it again. `POST /api/resume` should continue.
   Write the exact steps and what you saw in PROGRESS ("manual note"). Do not invent output.
6. PROGRESS: row 18, the verdict, the parity result, the known issues (config-hash note, in-process turn locks until 19).
7. Interview note `docs/notes/18-postgres-redis.md` per `docs/notes/TEMPLATE.md`. Its numbers come only from
   `eval/reports/orders_parity.md` and the committed smoke run. Run `make notes-check`.
8. One commit: `feat(platform): PostgreSQL with Alembic, Redis, durable LangGraph checkpoints and readiness checks`.
   Include this plan file in it.

## 6. Do not

- Do not make the graph, nodes or `OrderService` async.
- Do not change prompts, thresholds, intents, routes or refund rules. This commit moves state; it changes no behaviour.
- Do not run DDL or `PostgresSaver.setup()` at API startup.
- Do not move turn locks, add retries/timeouts/circuit breakers (19), or add caching (26).
- Do not commit `.env`, `.sqlite` files, database dumps or `items.jsonl`.
- Do not publish Postgres or Redis ports beyond `127.0.0.1`.
- Do not rebuild docs or re-ingest Milvus to silence a config-hash message.
- Do not promote a new baseline. `eval/baselines/main.json` stays as it is.
- Do not push.

## 7. Final message

Say what changed, how you verified it, every deviation from the task prompt (start from §1), and any follow-ups.
Then paste the full interview note.
