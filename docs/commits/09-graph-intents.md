# Commit 09 — LangGraph skeleton, query rewrite, 9-intent classifier

**Week 3 · depends on: 01 (can start in parallel with Week 2)**

## Context
The system is a **workflow with fixed edges**, not a free agent: every message goes rewrite → classify → one of 5 paths.
This commit builds the graph skeleton with stub path nodes, plus the two front nodes and their measurement.

9 intents → 5 paths (see `AGENTS.md` §6):
A tools: `order_status`, `shipping_delivery`, `talk_to_human` · B knowledge: `product_question`, `policy_question` ·
C after-sales: `refund_request`, `return_exchange` · D: `complaint` · E fixed: `chitchat_other`.

## Read first
- `AGENTS.md` §5.2, §5.5, §6
- `docs/DATA_NOTES.md` (Bitext intents and columns)
- LangGraph docs for `StateGraph`, conditional edges, checkpointers (use the installed version's API)

## Task
1. `src/support_agent/graph/intents.py` — `Intent` enum, `Path` enum, `INTENT_TO_PATH` dict (single source of truth).
2. `src/support_agent/graph/state.py` — `ConversationState` (TypedDict or Pydantic, as LangGraph prefers in the installed version):
   `messages`, `customer_id`, `rewritten_query`, `intent`, `intent_confidence`, `path`, `retrieval` (list of chunks, filled later), `gate` (result, filled later), `order_context`, `handoff` (payload or None), `answer`, `citations`, `trace` (list of node names visited, for tests and debugging).
3. `src/support_agent/graph/nodes/rewrite.py` — uses the `fast` model with the last N turns (config). Returns the original text unchanged when it is already self-contained (prompt says so; also skip the LLM call entirely for the first turn).
4. `src/support_agent/graph/nodes/classify.py` — `fast` model with **structured output** (`with_structured_output` → `{intent, confidence}`), prompt in `graph/prompts/classify.md` with a short definition and 2 examples per intent. Examples must not come from any eval test split. If parsing fails → `chitchat_other` with confidence 0 and log it.
5. `src/support_agent/graph/build.py` — `build_graph(deps) -> CompiledGraph` with a checkpointer (in-memory by default, SQLite saver optional via config).
   Edges: `START → rewrite → classify → route_by_path →` one stub node per path `→ END`. Stubs set `answer = "[path X not implemented]"`. Every node appends its name to `trace`.
   `deps` is a small dataclass (models, retriever, order service, settings) so tests inject fakes.
6. **Intent eval**
   - `src/support_agent/data/intent_map.py` — maps Bitext's 27 intents to our 9. Write the table with a one-line reason per row into `docs/INTENTS.md`. Suggested starting point (adjust after looking at real utterances):
     `track_order, change_order, cancel_order, place_order, check_invoice, get_invoice → order_status`; `delivery_options, delivery_period, change_shipping_address, set_up_shipping_address → shipping_delivery`;
     `contact_human_agent, contact_customer_service → talk_to_human`; `get_refund, track_refund → refund_request`; `check_refund_policy, check_cancellation_fee, check_payment_methods → policy_question`;
     `complaint, review(negative) → complaint`; account / newsletter / password intents → `policy_question` or `chitchat_other` (decide and justify).
   - Bitext has no `product_question`, `return_exchange` or chit-chat. Build `eval/sets/intent_extra.jsonl`: product questions from the **dev** split of the eval set + ~40 hand-written chit-chat/greetings + ~40 return/exchange utterances (LLM-drafted, then filtered for duplicates). Mark source on each.
   - `eval/intent_eval.py` + `make eval-intent`: stratified sample (e.g. 50 per intent, fixed seed) from Bitext held-out + extras. Reports accuracy, per-intent precision/recall, confusion matrix, and **path accuracy** (wrong intent but right path is less harmful). Writes `eval/reports/intent.md`.

## Requirements
- Routing is pure code from `INTENT_TO_PATH`; the LLM never picks the next node.
- Low confidence (< config `intent.min_confidence`) on a knowledge or after-sales intent is still routed, but flagged in state (the gate will be the safety net). Document this choice in `docs/INTENTS.md`.

## Tests
- For each of the 9 intents, a graph run with a fake classifier visits `rewrite → classify → <expected path stub>` (assert on `trace`).
- Rewrite is skipped on the first turn; with a follow-up ("what about the W40 Pro?") the fake model's output is used.
- Classifier parse failure → `chitchat_other`.
- Intent map covers all 27 Bitext intents.

## Out of scope
Real path logic (10–12).

## Done when
- [ ] `make eval-intent` produces a report on a real model; accuracy and path accuracy in PROGRESS (target ≥ 90%)
- [ ] `make check` green; PROGRESS row 09 updated
- [ ] Interview note `docs/notes/09-graph-intents.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(graph): LangGraph skeleton with query rewrite and 9-intent classifier plus intent eval
```
