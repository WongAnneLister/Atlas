# Commit 15 — Langfuse tracing and per-intent cost

**Week 4 · depends on: 13 (P1 feature, scheduled in week 4 because the README uses its numbers)**

## Context
We want every step of a conversation visible (rewrite, classify, retrieve, rerank, gate, answer, tools) and cost broken down
**by intent**, so we can say things like "refund conversations cost N× a policy question, because of X".
Langfuse is optional: with tracing disabled the app and evals behave exactly the same.

## Read first
- `AGENTS.md` §5.4 (optional services degrade to no-ops)
- `docker-compose.yml` (the `tracing` profile from commit 01)
- Langfuse LangChain/LangGraph integration docs for the installed SDK version

## Task
1. `src/support_agent/observability/tracing.py`:
   - `get_callbacks(conversation_id, customer_id) -> list` — returns the Langfuse callback handler when `tracing.enabled` and keys are set, else `[]`.
   - Session id = conversation id; user id = customer id (demo ids only).
   - After `classify`, set trace tags/metadata: `intent:<x>`, `path:<y>`; after the gate, add `gate_passed`, `gate_score`; on handoff add `handoff:<reason>`.
   - Non-LLM steps (retrieve, rerank, gate) appear as spans with inputs/outputs trimmed (top 5 chunk ids + scores, not full text).
2. Pass callbacks through the graph in the API and in `e2e_eval.py` (flag `--trace`).
3. `src/support_agent/observability/cost.py` — token usage → cost using a price table in config (per model, per 1M input/output tokens; values marked as "update me" with the date). Works **without** Langfuse, from the usage metadata already collected in commit 13.
4. Extend `eval/e2e_eval.py` output and `eval/reports/e2e.md` with a **cost by intent** table: mean/median tokens and cost per conversation, LLM calls per conversation, share of total cost. Add a sentence explaining the most expensive path from the data (e.g. number of LLM calls in that path).
5. `docs/OBSERVABILITY.md` — how to start Langfuse (`docker compose --profile tracing up -d`), env vars, a screenshot placeholder path `docs/img/langfuse_trace.png` (the human will take it), and what tags exist.

## Requirements
- With `tracing.enabled=false`, no Langfuse import happens at runtime (lazy import).
- No customer message text is sent to tracing when `tracing.redact_inputs=true` (default false for the demo; document it).

## Tests
- `get_callbacks` returns `[]` when disabled or keys missing; no import of `langfuse` in that case (check `sys.modules`).
- Cost calculation on fixture usage records; unknown model → cost `None` and a warning, not a crash.
- Cost-by-intent aggregation on a fixture run.

## Out of scope
Dashboards, alerts.

## Done when
- [ ] One manual traced conversation visible in local Langfuse with intent tags (say if you could not run Docker)
- [ ] `eval/reports/e2e.md` has the cost-by-intent table
- [ ] `make check` green; PROGRESS row 15 updated
- [ ] Interview note `docs/notes/15-langfuse-cost.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(observability): optional Langfuse tracing with intent tags and per-intent cost report
```
