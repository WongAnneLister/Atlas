# Commit 28 — ContextBuilder: budgeted, cache-aware context for every LLM call

**Phase 2 · Context management · depends on: 27**

## Context
Today each node builds its own messages: some pass the whole history, some the last N turns, tool outputs are pasted raw,
retrieved chunks have no global budget. Token use grows with conversation length (see the tokens-per-turn curve in
`eval/reports/sim.md`) and behaviour is hard to reason about.

Principle: **every LLM call gets a context assembled by one component, from typed sections, under an explicit budget, laid out
so the prompt prefix stays byte-stable across turns, with a recorded breakdown.**

Why the last part matters: providers (and self-hosted engines like vLLM/SGLang) reuse the KV cache of an **identical prompt
prefix**. One changed byte invalidates everything after it. The usual context-management moves — sliding windows that drop the
oldest turn, a summary rewritten every turn, re-trimming the middle — change the prefix every turn and push the cache hit rate
toward zero. Budgeting and caching pull in opposite directions; this commit designs for both and measures the trade-off.

## Read first
- `eval/reports/sim.md` (tokens per turn, redundant questions, fact retention baseline)
- Every node that calls a model: `rewrite`, `classify`, `plan`, `answer`, `tools_path`, `refund/decide`, `complaint`, grounding, guardrails
- Your provider's prompt-caching docs (breakpoint syntax, minimum cacheable length, TTL, how usage reports cache reads/writes) and how `langchain` exposes them (`usage_metadata.input_token_details`)

## Task
1. **Sections** — `src/support_agent/context/sections.py`: typed sections, each with a **stability layer**, a priority and a renderer:

   | Layer | Changes | Sections |
   |---|---|---|
   | `L0_global` | never (per deploy) | `system_instructions`, `safety_rules`, tool definitions (sorted by name), few-shot examples |
   | `L1_session` | once per conversation | `customer_profile` (long-term memory, filled in 30) |
   | `L2_compacted` | every K turns | `conversation_summary` blocks (filled in 29) |
   | `L3_history` | append-only | `recent_turns` (user + assistant messages; assistant turns keep citation ids, **not** the evidence text) |
   | `L4_turn` | every turn | `task_instructions` for this node, `retrieved_evidence`, `order_context`, `tool_results` of this turn, `pinned_facts`, current date, `user_message` |

   Rule: rendered order = layer order. Nothing from a later layer may appear before an earlier one.
2. **Per-node budget profiles** — `src/support_agent/context/budget.py`: a token counter interface (provider token-count endpoint or tokenizer if available; otherwise a calibrated approximation — measure and record its error) and a per-node profile in config: total budget, per-section min/max, trim order. Example: `answer` → evidence ≥ 40%, history ≤ 25%; `classify` → last 2 turns only (classify uses its own short prefix; it does not need the shared history).
3. **Builder** — `src/support_agent/context/builder.py`: `ContextBuilder.build(node, state) -> BuiltContext(messages, breakpoints, breakdown, dropped, prefix_hash)`:
   - Fill by priority; trim **only inside `L4_turn`** per turn: tool results via per-tool compressors (keep ids, statuses, dates, amounts), evidence lowest-rerank-first but never below the gate's `good_count` chunks.
   - `L0–L3` are **never trimmed per turn**. When history exceeds its budget, that is handled by compaction (commit 29), which changes the prefix only every K turns. Until 29 lands, use a temporary rule: hard cap on history turns, logged as a known cache-breaking fallback.
   - Never trim: system/safety rules, user message, order context needed for a refund decision. If they alone exceed the budget → `ContextOverflow` → node hands off (`context_overflow`).
   - `breakdown` = tokens per section and per layer; `dropped` = what was cut and why; `prefix_hash` = hash of the rendered L0–L3 bytes. All go to state and traces.
4. **Cache breakpoints, provider-agnostic** — the builder emits abstract breakpoints: after `L0`, after `L1`, after `L2`, and at the end of `L3`. `src/support_agent/context/cache_adapter.py` maps them per provider:
   explicit markers where the provider needs them (e.g. `cache_control` blocks — respect the max breakpoint count and minimum cacheable length; skip a breakpoint whose prefix is below the minimum), no-op for providers with automatic prefix caching. TTL per layer from config (longer for `L0`, default for the rest; longer TTLs must come first if the provider requires it).
5. **Shared prefix across nodes** — `L0` is identical for every node that uses the main conversation context (`rewrite`, `answer`, `tools_path`, `refund/decide`, `complaint`); node-specific instructions live in `L4_turn`. Side calls (summariser, judge-lite, grounding) that reuse conversation context must copy the parent's `L0–L3` verbatim and append their own instructions at the end.
6. **Kill silent invalidators** — no timestamps, request ids, customer names or flags interpolated into `L0`; current date goes to `L4`. Deterministic serialisation everywhere (`json.dumps(..., sort_keys=True, separators=...)`, sorted tool list, no set iteration). Dynamic operator instructions are appended as a late message, never by editing `L0`.
7. Refactor **all** model-calling nodes to use the builder and the adapter. Delete ad-hoc history slicing.
8. **Metrics** — record per call: input tokens, cache-read tokens, cache-write tokens (from usage metadata), `prefix_hash`, first-token latency. Expose `cache_hit_ratio = cache_read / input` per node in `/metrics` and in eval reports.
9. **Eval** — re-run `make eval-sim` and the e2e eval. Report vs the commit-27 baseline (paired, CIs): tokens per turn curve, cache hit ratio per node, cost per conversation, first-token latency P50/P95, task success, fact retention, redundant questions; plus the average breakdown per node and layer. Write `eval/reports/context.md`.

## Requirements
- No node may call a model without `ContextBuilder` (wrap `get_chat_model` so it requires a `BuiltContext`; add a test).
- Single-turn quality metrics must not get significantly worse.
- Cache features are optional: with a provider that has no caching, everything works and the hit ratio simply reports 0.

## Tests (no model calls)
- **Prefix stability**: simulate a 12-turn conversation with fakes; for consecutive turns, the rendered `L0–L3` of turn n is a byte-exact prefix of turn n+1 (append-only) except at compaction points; `L0` bytes are identical across customers and nodes.
- Silent-invalidator guards: rendering `L0` twice in different processes/times yields identical bytes; tool order is sorted; JSON is canonical.
- Budget respected for random section sizes (property-style); trim happens only in `L4`; never-trim sections never trimmed; overflow → handoff.
- Tool-result compressors keep the fields the refund decision needs (fixture orders).
- Cache adapter: breakpoint count ≤ provider max; breakpoints below the minimum length are skipped; no-op adapter emits plain messages.
- Breakdown sums to total tokens.

## Out of scope
Summaries and compaction (29), long-term memory content (30), the layout A/B experiment and KV-level benchmark (35).

## Done when
- [ ] `eval/reports/context.md`: tokens-per-turn curve, cache hit ratio per node, cost and first-token latency, quality metrics with CIs, breakdown per node and layer
- [ ] Prefix-stability tests green
- [ ] `make check` green; PROGRESS row 28 updated
- [ ] Interview note `docs/notes/28-context-builder.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
refactor(context): cache-aware ContextBuilder with stability layers, per-node budgets, provider cache adapter and traced breakdowns
```
