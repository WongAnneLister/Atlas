# AGENTS.md

Instructions for AI coding agents (Claude Code, Codex, Cursor, etc.) working in this repository.
Read this file fully before every task. If a task prompt conflicts with this file, follow this file and say so.

## 1. What this project is

An English e-commerce after-sales customer-service agent built on public datasets.
It answers policy and product questions with citations, handles order/shipping questions with tools,
runs a refund sub-flow, and **hands off to a human when the evidence is weak**.

The project exists to show three things, in this order:

1. **Reliability** — out-of-scope questions are never answered (false-accept = 0% on the no-answer set).
2. **Measured decisions** — every design choice has a before/after number from the eval scripts.
3. **Demo-ability** — a reviewer can clone, run one command, and see it work.

Full requirements: `docs/PRD.md`. Commit-by-commit plan: `docs/commits/00-INDEX.md`. Current state: `docs/PROGRESS.md`.

## 2. Tech stack (do not swap without being asked)

| Area | Choice |
|---|---|
| Language | Python 3.11, managed with `uv` |
| Orchestration | LangGraph (workflow with fixed edges + small agent loops inside nodes) |
| LLM access | `langchain.chat_models.init_chat_model`, model names from config/env only |
| Embeddings | BGE-M3 dense (1024 dims) |
| Lexical | BM25 via Milvus full-text search (sparse function) |
| Vector store | Milvus standalone (Docker Compose) |
| Fusion | Reciprocal Rank Fusion, k = 60, top 50 from each retriever |
| Reranker | BGE reranker (cross-encoder), keep top 5 |
| Orders | SQLite + a small `OrderService` (mock data, fixed seed) |
| API | FastAPI, Server-Sent Events for streaming |
| UI | One static HTML page served by FastAPI (no frontend build step) |
| Tracing | Langfuse (optional; app must run without it) |
| Tests | pytest; ruff for lint + format; mypy on `src/` |

**Phase 2 (production) additions — allowed only from the commit that introduces them:**

| Area | Choice | Introduced in |
|---|---|---|
| Relational store | PostgreSQL + Alembic migrations (orders, checkpoints, memory, handoffs, feedback) | 18 |
| Cache / locks / rate limit | Redis | 18 |
| Graph checkpoints | LangGraph Postgres checkpointer | 18 |
| Metrics | Prometheus client (`/metrics`), OpenTelemetry-compatible names | 19 |
| Load testing | Locust | 33 |
| Statistics | bootstrap CIs with numpy/scipy | 17 |

## 3. Repository layout

```
configs/default.yaml        # every threshold, weight, model name, top-k lives here
src/support_agent/
  config.py                 # loads YAML + env into a typed Settings object
  llm.py                    # get_chat_model(role) — the ONLY place models are created
  data/                     # download, license check, policy-doc builder
  orders/                   # SQLite schema, seed generator, OrderService
  retrieval/                # chunking, embedding, Milvus store, hybrid + RRF, rerank
  gate/                     # evidence gate (4 signals -> score -> pass/handoff)
  graph/                    # LangGraph state, intents, nodes, build_graph()
  context/                  # (phase 2) ContextBuilder: one place that assembles every LLM prompt under a token budget
  memory/                   # (phase 2) short-term layers + long-term customer memory
  guardrails/               # (phase 2) input/output checks, PII redaction
  reliability/              # (phase 2) timeouts, retries, fallback, circuit breaker, idempotency, locks
  handoff/                  # (phase 2) human handoff queue + agent console
  api/                      # FastAPI app, SSE endpoint, static/index.html
  observability/            # Langfuse wiring, cost accounting, Prometheus metrics
docs/notes/                 # one interview note per commit (AGENTS §9); TEMPLATE.md has the rules
.claude/commands/           # /interview-note, /drill
eval/
  sets/                     # eval JSONL files (generated; see data rules)
  reports/                  # generated markdown/CSV reports — committed
  *.py                      # eval scripts, one entry point per experiment
data/raw/                   # downloaded datasets — NEVER committed
data/processed/             # built docs/chunks — committed only if licenses allow
tests/
docs/
```

## 4. Commands

Always use the Makefile targets; add a target when you add a new entry point.

```bash
make setup        # uv sync + pre-commit install
make up           # docker compose up -d (Milvus; Langfuse if enabled)
make data         # download datasets + license report + build policy docs + seed orders
make ingest       # chunk + embed + load into Milvus
make eval-retrieval   # 4 retrieval configs -> eval/reports/retrieval.md
make eval-e2e     # full graph on the eval set -> eval/reports/e2e.md
make sweep        # gate threshold sweep -> eval/reports/threshold_sweep.md (+ png)
make serve        # uvicorn on :8000, chat page at /
make check        # ruff + mypy + pytest (must pass before every commit)
```

## 5. Hard rules

### 5.1 Honesty of numbers (most important)
- Every number in README or reports must come from a script in `eval/` that anyone can re-run. Never type a metric by hand.
- Reports record: git SHA, config hash, model names, dataset versions, date, eval split.
- Thresholds and weights are **tuned on the `dev` split and reported on the `test` split**. Never tune on `test`.
- Never edit eval questions or gold labels to make a metric go up. If a label is wrong, fix it in a separate commit with the reason in the message.
- Do not copy numbers from any other project (including the author's previous work). This project reports only its own results.
- If a target in the PRD is missed, report the real number and the reason. Do not hide it.

### 5.2 Safety behaviour of the agent
- The evidence gate cannot be bypassed. Any path that produces a knowledge answer must go through `gate.evaluate()`.
- If the gate fails, the reply is a handoff, not a guess. The handoff payload includes the conversation, the rewritten query, and the retrieval snapshot.
- Refund decisions always read the order from `OrderService` and the policy from retrieval. The LLM never invents order facts.
- Agent loops (ReAct inside a node) have a hard step cap from config (default 5). On cap, hand off.
- Prompts live in `src/support_agent/graph/prompts/` as `.md` or `.txt` files, not inline strings longer than 3 lines.

### 5.3 Data and licenses
- `data/raw/` is gitignored. The repo ships download scripts, not datasets, unless `docs/LICENSES.md` says redistribution is allowed.
- Mock orders are generated from a fixed seed; the generator is committed, the `.sqlite` file is not.
- No real personal data anywhere. Fake names/emails must use `example.com`.

### 5.4 Configuration
- No magic numbers in code. Thresholds, weights, top-k, RRF k, step caps, model names → `configs/default.yaml`.
- Secrets only from env (`.env`, see `.env.example`). Never commit `.env`.
- The app must start with only `LLM_*` env vars set. Langfuse and anything optional degrade to no-ops.

### 5.5 Tests
- Unit tests run **offline**: no network, no Milvus, no real LLM. Use fakes (`FakeListChatModel`, an in-memory retriever, a deterministic fake embedder).
- Integration tests that need Milvus or a real LLM are marked `@pytest.mark.integration` and skipped by default.
- Every bug fix comes with a test that fails before the fix.
- Graph tests assert the **route taken** (node sequence), not just the final text.

### 5.6 Code style
- Type hints everywhere in `src/`. Pydantic models for anything crossing a boundary (API, graph state, eval records).
- Small functions; no file over ~300 lines without a reason.
- Log with `structlog` or stdlib `logging`, never `print` in `src/`.
- English for all code, comments, docs, commit messages.

### 5.7 Production principles (phase 2, commits 17+)
- **Eval first.** Every phase-2 feature starts by adding or extending the eval that will judge it, then the feature, then a before/after report with confidence intervals (`make eval-compare`). A feature that does not move its metric, or that hurts another one, is reported as such — not hidden.
- **Release gate.** Nothing merges if the CI eval gate fails: no-answer false-accept > 0, red-team attack success > its budget, or any core metric dropping beyond its CI.
- **Fail closed.** If a dependency the safety path needs is down (reranker, retrieval, policy store), the knowledge and refund paths hand off. They never answer with weaker evidence than the gate was calibrated on.
- **Idempotent side effects.** Every write that a retry could repeat (refund requests, handoffs, memory writes) carries an idempotency key.
- **Context is engineered, not appended.** From commit 28 on, every LLM call gets its messages from `ContextBuilder`, with a per-section token budget and a recorded token breakdown. No node concatenates history by hand.
- **Prefix-stable layout.** Context is rendered in stability layers: `L0_global` → `L1_session` → `L2_compacted` → `L3_history` (append-only) → `L4_turn`. Per-turn trimming happens only in `L4`; history shrinks only by chunked compaction into frozen summary blocks. Never put timestamps, ids, names or flags in `L0`; serialise deterministically. A change that breaks the prefix-stability tests needs a written reason and a cache-hit-ratio number in its report.
- **Memory writes are policy-driven.** What may be stored, for how long, and how it is deleted is code + config, tested, and documented. Memory never crosses customers.
- **Everything observable.** Each request has a trace id that appears in logs, Langfuse, metrics labels (low-cardinality only), and the handoff payload.

## 6. Domain model (shared vocabulary)

**9 intents → 5 paths**

| Intent | Path |
|---|---|
| `order_status`, `shipping_delivery`, `talk_to_human` | **A. tools** — agent calls OrderService tools (or hands off for `talk_to_human`) |
| `product_question`, `policy_question` | **B. knowledge** — retrieve → rerank → gate → cited answer or handoff |
| `refund_request`, `return_exchange` | **C. after-sales** — get order (interrupt to let user pick if missing) → retrieve policy → decide |
| `complaint` | **D. complaint** — short empathetic reply, then handoff |
| `chitchat_other` | **E. fixed** — template reply, no LLM call |

**Evidence gate — 4 signals** (weights in config, defaults shown)
1. `top_score` — top-1 rerank score (sigmoid-normalised), weight 0.5
2. `good_count` — number of chunks with score ≥ `good_evidence_min`, capped at 3, divided by 3, weight 0.2
3. `margin` — top-1 minus top-2 score, clipped to [0, 1], weight 0.15
4. `key_hit` — key terms of the query (model numbers, amounts, policy nouns) found in top chunks, weight 0.15

`score = Σ weight × signal`; pass if `score ≥ threshold`. The threshold is chosen by `make sweep`, never hard-coded from memory.

**Eval set** — 300 questions, 5 groups × 60: `basic_policy`, `model_number`, `colloquial`, `cross_doc`, `no_answer`.
Each record: `id, group, split (dev|test), question, gold_sections[], answer_points[], answerable, reviewed`.

## 7. How to work on a task

1. Read `AGENTS.md`, `docs/PROGRESS.md`, and the commit prompt you were given.
2. Inspect the real data/code before assuming a schema. If something in the prompt does not match reality, adapt and write the difference in your final message.
3. Make the change. Keep the diff inside the prompt's scope; note anything else as a follow-up.
4. Run `make check`. Fix until green.
5. Update `docs/PROGRESS.md` (what is done, numbers produced, known issues).
6. Write the **interview note** `docs/notes/NN-<slug>.md` (see §9). Run `make notes-check`.
7. Make **one** commit with the message given in the prompt (Conventional Commits), including the note. Do not push unless asked.
8. Final message: what changed, how it was verified, any deviations, any follow-ups — then **paste the full interview note** at the end.

## 9. Interview notes (required for every commit)

The author will explain this project in English interviews. After each commit, answer five questions in `docs/notes/NN-<slug>.md`,
using the exact format and rules in `docs/notes/TEMPLATE.md`:

1. **What** — what this commit built.
2. **Why** — the problem it solves; what breaks without it.
3. **Number** — real numbers from `eval/reports/` or `eval/runs/`, with the source path. If none: "No number yet. I will measure it in commit NN."
4. **Trade-off** — what was given up and what it costs.
5. **Likely follow-up question** — the one question an interviewer will most likely ask next, and a short answer.

Language rules (strict): simple spoken English, max 15 words per sentence, one idea per sentence, common words, explain a technical term the first time, first person ("I built…"), no invented numbers, honest about misses. 2–4 sentences per section.
The note describes what **this commit actually did**, including deviations from the prompt. Do not describe planned work as done.

## 8. Do not

- Do not add new frameworks (LlamaIndex, Haystack, a JS frontend, a different vector DB, Kubernetes). Phase-2 additions in §2 are the only exceptions.
- Do not start a phase-2 commit before Checkpoint 4 (v1 shipped) is marked in PROGRESS.
- Do not call an LLM inside unit tests.
- Do not commit data dumps, `.sqlite`, model weights, `.env`, or notebooks with outputs.
- Do not let the LLM decide whether to retrieve on the knowledge path; retrieval is a fixed edge.
- Do not lower the gate threshold to raise the pass rate without re-running the sweep and recording false-accept.
