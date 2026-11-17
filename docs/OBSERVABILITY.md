# Observability: Langfuse tracing and cost by intent

Tracing is optional. With `tracing.enabled: false` (the default), or without both Langfuse keys,
the app and the evals run exactly the same and the `langfuse` package is never imported.
Cost accounting does not need Langfuse at all.

## Start local Langfuse

```bash
LANGFUSE_PORT=3010 docker compose --profile tracing up -d langfuse-web langfuse-worker
```

`LANGFUSE_PORT` defaults to 3000; pick another port if 3000 is taken. The web UI binds to
`127.0.0.1` only. The first start builds the pinned MinIO image from source and pulls the
Langfuse, ClickHouse, Postgres and Redis images, so it takes several minutes.

The first start also creates a local organisation, a project and a login (headless init in
`docker-compose.yml`). These are **local development values only**:

| Item | Value |
|---|---|
| UI | `http://localhost:<LANGFUSE_PORT>` |
| Login | `dev@example.com` / `local-dev-password` |
| Project | `support-agent` |
| Public key | `pk-lf-local-dev` |
| Secret key | `sk-lf-local-dev` |

Never reuse them for a shared or public Langfuse.

## Turn tracing on

Set these in `.env` (see `.env.example`):

```
SUPPORT_AGENT__TRACING__ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-local-dev
LANGFUSE_SECRET_KEY=sk-lf-local-dev
LANGFUSE_HOST=http://localhost:3010
```

Then:

- **Chat page:** `make serve`. Every chat request and every order-picker resume is one trace.
- **Evaluation:** `make eval-e2e EVAL_E2E_ARGS="--trace ..."`. Every eval item is one trace.

If Langfuse is down, spans are dropped in the background and the request still completes.

## What a trace contains

One root span per turn (`chat_turn`, `resume_turn` or `e2e_item`). Below it, the LangChain
callback adds one span per graph node (rewrite, classify, retrieve, gate, answer, tools,
refund steps, handoff) and one generation per LLM call, with token usage.

- **Session id** = conversation id (the eval uses its thread id). **User id** = demo customer id.
- **Tags**, set when the turn ends:
  - `intent:<intent>` and `path:<A-E>`
  - `gate_passed:true|false` when the gate ran
  - `handoff:<reason>` when the turn handed off
  - `error` when the turn raised
- **Metadata**: `gate_score` (4 decimals) and `error_type`.
- **Retrieval data is trimmed.** Any list of retrieved chunks keeps the first `tracing.max_chunks`
  (default 5) as `chunk_id`, `section_id` and scores. Chunk text is never sent. Rerank runs inside
  the `retrieve` node, so its scores appear in that span; there is no separate rerank span.
- **LLM generations** keep their full prompts, including source text, so you can debug an answer.
  The `answer` span also carries the model's evidence quotes, which are short excerpts of sources.
- The trace list shows the name `LangGraph` (set by the LangChain callback). The root span under
  it is named `chat_turn`, `resume_turn` or `e2e_item`.
- Tags are written when the turn ends. Langfuse may show them a few seconds after the spans.

Verified on 2026-11-17 against Langfuse 3.227.1 with SDK 5.2.0: a Flipkart return question gave
one trace with session, user, `intent:policy_question`, `path:B`, `gate_passed:true` and
`gate_score`; the `retrieve` span held chunk ids and scores only. A gold-bars question added
`handoff:incomplete_evidence`.

## Redacting customer text

`tracing.redact_inputs` is `false` for the demo. Set it to `true` to replace customer text with
`[redacted]` before it leaves the process: human/user message content anywhere in a span (state,
handoff payload, LLM prompts) and `rewritten_query`. Agent replies are still sent. The redaction
runs in the Langfuse client's mask hook and is covered by `tests/test_observability.py`.

## Cost by intent

`UsageLedger` (`src/support_agent/observability/cost.py`) counts LLM calls and tokens per model
name the provider reports. `cost_usd` prices them with `costs.prices` in `configs/default.yaml`.
A model without a price gives cost `None` and one warning, never a guess.

The chat API reports `llm_calls`, `usage` and `cost_usd` in each `done` event. `make eval-e2e`
stores per-model usage on every record and writes a **Cost by intent** table in its report.

To price a finished run after filling `costs.prices`, without new model calls:

```bash
make eval-e2e EVAL_E2E_ARGS="--output <run.jsonl> --report <report.md> --report-only"
```

## Screenshot

A screenshot of one traced conversation belongs at `docs/img/langfuse_trace.png`
(to be taken by a human from the local UI).
