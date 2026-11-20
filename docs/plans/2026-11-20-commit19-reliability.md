# Commit 19 execution plan — reliability: timeouts, retries, fallback, fail-closed, idempotency, locks, metrics

Read this together with `docs/commits/19-reliability.md` (the task) and `AGENTS.md` (the rules).
This plan keeps the goal of the task. It fixes the places where the task prompt does not match the
repository as of 2026-11-20 (`main` = `5fbeb90`), and it orders the work.
If this plan and `AGENTS.md` disagree, follow `AGENTS.md` and say so.

## 0. Preconditions (check first; stop and report if one fails)

1. **Branch.** Start from `main` at `5fbeb90` or later. Work on `codex/c19-reliability`. Do not push.
2. `make check` is green before you change anything.
3. **State services.** Atlas Postgres (`127.0.0.1:5433`) and Redis (`127.0.0.1:6379`) run in Docker
   (`support-agent-postgres-1`, `support-agent-redis-1`). Port 5432 belongs to other projects. Never use it.
4. **Milvus** is on a VPS behind an SSH tunnel on `127.0.0.1:19530`. If it drops, stop and ask the author.
5. **LLM.** For eval targets, load `.env` first: `set -a; source .env; set +a`. Never print or commit its values.

## 1. Facts about the repository that change the task

| Task prompt says | Reality | What to do instead |
|---|---|---|
| Build the fail-closed rules | Most already exist. A retrieval exception gives empty chunks, then the gate fails, then a `retrieval_error` handoff. An answer-model exception gives an `answer_error` handoff. A classifier exception falls back to `chitchat_other`. | Do not rebuild them. Add the reason `dependency_unavailable` for **dependency** failures: timeouts, connection errors, 429/5xx after retries, and an open circuit. Other exceptions (bugs, bad data) keep their current reasons. Keep filling `retrieval_error_type`, `answer_error_type` and `classification_error_type`; `eval/gate.py` and `eval/e2e_diagnostics.py` count them. Add `dependency_unavailable` to the reasons that `eval/gate.py::dependency_errors` counts, and add a test. |
| Classifier fails → `chitchat_other` reply that offers a human | Today it goes to the generic `fallback` fixed reply. That reply does **not** offer a human (`graph/prompts/fixed_replies.yaml`). | Add a `classification_failed` fixed template that offers a human. The fixed node picks it when `state.classification_failed` is true. It still makes no LLM call. |
| Retry LLM calls | LangChain's OpenAI-compatible clients, DeepSeek included, already retry inside the SDK. `ChatDeepSeek.max_retries` is unset, so the openai client's default of 2 applies. | Our retry layer becomes the only one. Pass `max_retries` from config (`llm.provider_max_retries: 0`) in `get_chat_model`. Check that each supported provider accepts the kwarg. Otherwise attempts multiply (3 × 3 = 9) and blow the time budget. Add a test that the kwarg is passed. |
| Per-call timeouts for rewrite, classify, answer, decide | Models are built once per **role** (`fast`, `main`) with `llm.timeout_s` (30 s). Nodes share them. | Keep `llm.py` the only place that builds models. Cache model instances by `(role, model name, timeout)` in `GraphDeps`, so each call site gets its configured timeout without per-request hacks. |
| Reranker timeout | The reranker is an **in-process** BGE cross-encoder on MPS or CPU. A Python thread cannot be cancelled. | Run rerank in a dedicated single-worker executor and wait with the configured timeout. On timeout, abandon the wait and count a failure, so the circuit opens. Because there is a single worker, a hung call cannot stack new ones. Write this limit in `docs/RELIABILITY.md`. |
| Refund idempotency key + unique constraint | Commit 18 already makes `request_id` = uuid5(customer, order, turn message id), with on-conflict replay. | Keep that. Add an explicit `idempotency_key` column with a UNIQUE constraint (Alembic `0002`; SQLite through the same metadata). The key is `conversation_id + turn_id + action`. The node reads `thread_id` with `langgraph.config.get_config()`; do not add it to the graph state. A replay with the same key returns the existing row (one row); a different payload under the same key still raises (existing behaviour → handoff). |
| Handoff creation takes an idempotency key | Handoffs are **not persisted** yet. The queue arrives in commit 31; today the payload lives only in graph state. | Add a deterministic `idempotency_key` field to `HandoffPayload`, built the same way. Create no table now. `docs/RELIABILITY.md` says commit 31 adds the unique constraint when it adds the queue. |
| Redis lock per conversation | `api/app.py` keeps an in-process `dict[str, asyncio.Lock]`. The 18 `KeyValueStore` has `set_if_absent` but no owner-safe release. | Add `delete_if_value(key, token)` (a Lua compare-and-delete in `RedisStore`, the same semantics in `NullRedis`). The lock holds an owner token and a TTL from config that is longer than the whole turn budget. Use it for `/api/chat` and `/api/resume`. A busy lock → 409, detail `Still answering your previous message. Please wait.` (the UI already shows `detail`). Redis unreachable while acquiring → **503**; never run the turn without the lock. In `local`, `NullRedis` gives the same behaviour in one process. |
| Circuit counts in Redis or in-process | — | Use in-process, per worker, with an injected clock. It stays simple, adds no Redis call in the hot path, and needs no network in tests. Write the trade-off (each worker learns on its own) in `docs/RELIABILITY.md`. |
| Prometheus `/metrics` | `AGENTS.md` §2 allows `prometheus-client` from commit 19. The API runs one uvicorn worker. | Add the dependency. Use an injectable `CollectorRegistry` so tests stay isolated. Note multiprocess mode (`PROMETHEUS_MULTIPROC_DIR`) as a follow-up for several workers. |
| `make chaos` runs the smoke eval with faults | Smoke runs are what `make eval-gate` and `make eval-baseline` accept. | A chaos run is `kind: "chaos"`, so the gate and promotion refuse it (test this). Fault injection lives in config `chaos:`, off by default, with a seeded RNG. `prod` refuses to start with chaos enabled. Inject faults at our wrapper layer, not by monkeypatching provider SDKs. |
| `config.py` | It is already about 460 lines. | Put the new settings models in `reliability/settings.py` and import them, as `db/settings.py` does. |
| One commit with the numbers | In commit 18 the smoke run was collected on a dirty tree (`dirty: true`), which is weaker evidence. | Make **two** commits. Commit 19 holds the code, tests, docs and note; its Number section says "No number yet. I will measure it in commit 19a." Then run the smoke and chaos evals on that **clean** commit and commit the run records, `eval/reports/chaos.md`, PROGRESS and a 19a note as `chore(eval): commit 19 smoke compare and chaos report`. |
| — | The Postgres checkpointer uses a msgpack allowlist (`graph/postgres.py::checkpoint_serializer`). | Every new Pydantic or enum type stored in `ConversationState` must join that allowlist. Otherwise restart-resume breaks. The restart-resume integration test must still pass. |

## 2. Design (fixed here so the work does not drift)

### 2.1 Settings — `reliability/settings.py`, values in `configs/default.yaml`
- `timeouts_s`: rewrite, classify, answer, decide, order_extract, grounding, complaint, tools, rerank, milvus, orders_db.
  LLM values must not exceed `llm.timeout_s`. Milvus keeps `milvus.timeout_s` as its source. Do not duplicate it; validate the relation.
- `retry`: max_attempts (default 3), base_delay_s, max_delay_s, jitter ratio, and a per-call `budget_s` that caps the total time of all attempts.
- `circuit`: failure_threshold, cool_down_s, half_open_max_calls (1).
- `llm.fallbacks: {fast: [], main: []}`: empty by default, so nothing changes. Env overrides `LLM_FAST_FALLBACKS` / `LLM_MAIN_FALLBACKS` (comma lists) follow the `LLM_*` pattern in `llm.py`.
- `llm.provider_max_retries: 0`.
- `locks`: conversation_ttl_s. A validator checks that it exceeds the sum of the turn's worst-case budgets.
- `chaos`: enabled (false), seed, llm_timeout_rate, llm_rate_limit_rate, llm_garbage_rate, rerank_down_rate, milvus_down_rate, orders_down_rate.
  The prod validator rejects `enabled: true`.

### 2.2 Error classes and retry — `reliability/errors.py`, `reliability/retry.py`
- `is_retryable(error)` is True for timeouts, connection errors, HTTP 429 and 5xx (by status attribute, across openai/httpx/anthropic types), `CircuitOpen`, and our `InjectedTimeout`/`InjectedRateLimit`.
  It is False for validation, parsing, 4xx (other than 429), `OrderNotFound` and `InvalidRefundRequest`.
- `retry_call(fn, *, policy, sleep, clock, rng, is_idempotent)`: exponential backoff with jitter, bounded by `max_delay_s` and the budget.
  It refuses (raises at call time) to retry a call marked non-idempotent. The refund write counts as idempotent only when it carries a key.
- `sleep`, `clock` and `rng` are injected, so tests run in zero real time.

### 2.3 Circuit breaker — `reliability/circuit.py`
- States closed → open after N consecutive retryable failures → half-open after the cool-down → closed on success / open on failure.
- One registry keyed by dependency name: `llm:<model>`, `reranker`, `milvus`, `orders_db`. Expose the state for metrics.
- An open circuit raises `CircuitOpen` immediately, without calling the dependency.

### 2.4 Model calls — `reliability/llm_calls.py`
- `ReliableModels(deps)` exposes `invoke(call_site, role, messages)` and `structured(call_site, role, schema, messages)`.
  Every node uses it instead of `deps.model(...)`. Models still come only from `llm.get_chat_model`.
- Per attempt: circuit check → timeout from `timeouts_s[call_site]` → call. Retry runs on retryable errors.
  When the chain is exhausted on retryable errors, the call moves to the next model in `llm.fallbacks[role]`.
  It never falls back on a parse error; repair (§2.5) handles those.
- Each call returns the result plus a small record: call site, role, the model that answered, attempts, `fell_back`, `repaired`, and the error type.
  Nodes store `answered_by_model: dict[str, str]` (call site → model) and append to `reliability_events` in state.
  Keep events small: names and counts only, never prompt or customer text.

### 2.5 Structured-output repair
- On a parse or validation failure, make exactly **one** repair call. It sends the same messages plus a repair instruction from
  `graph/prompts/repair.md` and the validation error text, cut to a configured length. Then validate again.
- If the repair fails too, return the node's existing safe default:
  classify → `classification_failed` fixed reply; answer → `invalid_answer` handoff; refund decide → its current safe handoff;
  order grounding → its current fallback.
- A repaired answer still goes through `render_covered_answer` and the citation check. A repaired refund decision still goes through
  the code-checked return window. Repair can never skip a check.

### 2.6 Dependency guards
- Wrap the retriever (Milvus call and rerank call separately) and `OrderService` reads/writes with timeout + circuit + retry.
  Reads are idempotent. `create_refund_request` is retried only with its idempotency key.
- On a dependency failure:
  - knowledge path → `dependency_unavailable` handoff with **zero** answer-model calls;
  - refund path → the same, before any decision call;
  - tools path → `dependency_unavailable` handoff (keep `tool_error` for non-dependency tool failures).
- `docs/RELIABILITY.md` holds one table row per dependency: dependency down → detection → behaviour → handoff reason → test name.

### 2.7 Conversation lock — `api/locks.py`
- `acquire(thread_id)` → a token, `None` when the lock is busy, or an error when the store is down. Release uses `delete_if_value`.
- Release happens in the same `finally` that `TurnResponse` already uses, so a closed SSE stream still releases.
- Tests: two concurrent requests → one 200 and one 409. Release by a non-owner is a no-op. TTL expiry frees a crashed holder. Store down → 503.

### 2.8 Metrics — `observability/metrics.py`, `GET /metrics`
- `atlas_requests_total{endpoint, outcome}`, `atlas_request_seconds{endpoint}`
- `atlas_llm_calls_total{role, model, outcome}`, `atlas_llm_seconds{role, model}`
- `atlas_retries_total{dependency}`, `atlas_fallbacks_total{role}`, `atlas_repairs_total{call_site, outcome}`
- `atlas_circuit_state{dependency}` (0 closed, 1 half-open, 2 open)
- `atlas_handoffs_total{reason}`, `atlas_gate_evaluations_total{passed}`, `atlas_path_total{path}`
- Labels come only from enums or config names. Add a test that walks the registry and fails on any label outside an allowlist.
  Never put customer, conversation, order or trace ids in labels.

### 2.9 Chaos
- `tests/chaos/`: fake models that time out, return 429, return garbage, or raise; a fake reranker that is down; a fake orders DB that is down.
  The tests cover each fail-closed row of the table.
- Fault injection: a `ChaosInjector(settings.chaos)` hooks into `ReliableModels` and the dependency guards, with a seeded RNG.
- `make chaos` = smoke set + `configs/chaos.yaml` overlay (20% LLM timeouts, reranker down for 50% of calls) → run record `kind: chaos`
  → `eval/reports/chaos.md`: answer rate, handoff reasons, retries, fallbacks, repairs, and **no-answer false accepts** (must be 0, with the rule-of-three/Wilson bound).
  The report records git SHA, config hash, models, dataset version, date and split (`AGENTS.md` §5.1).

## 3. Order of work (each step ends with `make check` green)

1. Settings + config + prod guard (chaos, budgets) + tests.
2. Error classes, retry and circuit breaker (pure, fake clock) + tests.
3. `get_chat_model` passes `provider_max_retries`. `ReliableModels` with timeouts, retry, fallback and `answered_by_model`. Move every node onto it.
4. Structured-output repair + `repair.md` + tests per call site.
5. Dependency guards + `dependency_unavailable` + the `classification_failed` template + `eval/gate.py` counting + tests.
6. Migration `0002` (`idempotency_key` UNIQUE) + refund key + handoff payload key + the checkpoint serializer allowlist.
7. Conversation lock (`delete_if_value`, 409/503) + tests.
8. Metrics + `/metrics` + the label allowlist test.
9. Chaos fakes in `tests/chaos/`, the injector, `make chaos`, the report script.
10. `docs/RELIABILITY.md`.
11. Commit 19 (code), with the note's Number section pointing to 19a.
12. Evidence on the clean commit (§5), then commit 19a.

## 4. Tests (offline unless marked)

- Retry happens only on retryable errors. Backoff is bounded, and total time ≤ budget (fake clock). There is no retry of a non-idempotent write.
- `get_chat_model` passes `max_retries=0`.
- The fallback chain is used in order, only on retryable errors, and `answered_by_model` is recorded. Empty fallbacks → behaviour as today.
- The circuit opens after N failures, half-opens after the cool-down, and closes or reopens correctly.
- Reranker down → knowledge path route `rewrite, classify, retrieve, gate, handoff`, reason `dependency_unavailable`, **0** answer-model calls.
- Milvus down → the same. Orders DB down → the tools and refund paths hand off with no refund row.
- Classifier exception → fixed reply that offers a human, with no extra LLM call.
- Garbage structured output → exactly one repair call, then a valid result or the safe default.
- Duplicate refund with the same key → one DB row (SQLite offline; Postgres under `integration`).
- Concurrent requests on one conversation → one runs, one gets 409. Store down → 503.
- The metrics label allowlist. The chaos injector is deterministic for a seed. Prod rejects chaos.
- A chaos run is refused by `make eval-gate` and `make eval-baseline`.
- Graph tests assert the route (node sequence), as `AGENTS.md` §5.5 requires.
- Integration: migration `0002` up/down; Postgres duplicate key; restart-resume still passes with the new state fields.

## 5. Verification and evidence (after commit 19, on a clean tree)

1. `make check` green; `make up-state && make migrate`; integration tests green.
2. `ENV=dev make eval-smoke`, then `make eval-gate RUN=<run dir>` against `eval/baselines/main.json`.
   The manifest must show `dirty: false` and the commit-19 SHA. Expect "Passed".
   Retries or repair may lower dependency errors or `invalid_answer` handoffs. Report every change with its verdict; do not hide one.
   Do not re-run until it passes. Do not promote a baseline.
3. `ENV=dev make chaos` → `eval/reports/chaos.md`. False accepts must be 0. If they are not, stop and report; that is a release blocker.
4. Manual: `ENV=dev make serve`; send two fast requests on one conversation (second → 409); `curl /metrics` shows the families above
   with no id labels. Write the steps and what you saw in PROGRESS. Do not invent output.
5. Commit 19a: run records (`manifest.json`, `metrics.json`; never `items.jsonl`), `eval/reports/chaos.md`, PROGRESS rows 19/19a,
   and `docs/notes/19-reliability-evidence.md`. `make check` and `make notes-check` green.

## 6. Do not

- Do not create chat models outside `llm.py`, or call a real LLM in unit tests.
- Do not change prompts (other than adding `repair.md` and the new templates), thresholds, intents, routes or refund rules.
- Do not let a fallback model, a repair or a retry bypass the gate, the coverage check, the citation check or the return-window check.
- Do not retry a write without an idempotency key.
- Do not run a turn without the conversation lock.
- Do not put ids or free text in metric labels.
- Do not add guardrails (21), caching (26) or load tests (33).
- Do not promote a baseline. Do not push.

## 7. Final message

Say what changed, how you verified it (commands and results), every deviation from the task prompt (start from §1), and the follow-ups.
Then paste both interview notes (19 and 19a).
