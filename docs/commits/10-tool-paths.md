# Commit 10 — Path A (order tools), D (complaint), E (fixed replies), and handoff

**Week 3 · depends on: 04, 09**

## Context
Three of the five paths do not need retrieval:
- **A. tools** — `order_status`, `shipping_delivery`: a small ReAct loop inside one node calls `OrderService` tools; `talk_to_human` goes straight to handoff.
- **D. complaint** — one short empathetic reply, then handoff.
- **E. fixed** — `chitchat_other`: template reply, **no LLM call**.
All handoffs share one payload format, which the knowledge and refund paths will reuse.

## Read first
- `AGENTS.md` §5.2, §6
- `src/support_agent/orders/service.py`, `graph/build.py`, `graph/state.py`

## Task
1. `src/support_agent/graph/handoff.py` — `HandoffPayload` (reason enum: `user_requested, complaint, low_evidence, agent_step_cap, tool_error, order_not_found, policy_requires_human`; conversation; rewritten query; intent; retrieval snapshot (may be empty); order context; created_at) and `make_handoff(state, reason) -> state update`.
   The customer-facing text is a template per reason in `graph/prompts/handoff_messages.yaml`.
2. `src/support_agent/graph/tools.py` — LangChain tools wrapping `OrderService`: `get_order`, `list_recent_orders`, `get_tracking`.
   `customer_id` is **injected from state**, never taken from the model's arguments (the model must not be able to read other customers' orders). Tool errors become a short error string for the model, plus a counter in state.
3. `src/support_agent/graph/nodes/tools_path.py`:
   - A bounded ReAct loop with the `main` model bound to the tools. Hard cap `agent.max_steps` (config, default 5). On cap or 2 consecutive tool errors → handoff (`agent_step_cap` / `tool_error`).
   - System prompt in `graph/prompts/tools_path.md`: answer only from tool results; if the order id is ambiguous, list recent orders and ask the user to pick; never promise refunds or dates not in the data.
   - `talk_to_human` → immediate handoff (`user_requested`), no LLM call.
4. `src/support_agent/graph/nodes/complaint.py` — `fast` model writes ≤ 2 sentences of acknowledgement (prompt: no promises, no compensation offers), then handoff (`complaint`).
5. `src/support_agent/graph/nodes/fixed.py` — picks a template from `graph/prompts/fixed_replies.yaml` (greeting, thanks, goodbye, capabilities, fallback) by simple keyword rules; no LLM.
6. Replace the stubs for paths A, D, E in `build.py`.

## Requirements
- Every tool call and its result are appended to `trace` (name + short args), for tests and later tracing.
- No path may return an empty answer: either an answer or a handoff message.

## Tests (fakes only)
- Order status: fake model calls `get_order` then answers → trace shows the tool call; answer contains the status from the DB.
- Model tries to pass a different `customer_id` → ignored; the injected one is used.
- Step cap: a fake model that calls tools forever → handoff with `agent_step_cap` after exactly `max_steps`.
- `talk_to_human` → handoff, zero LLM calls (count calls on the fake).
- Complaint → reply + handoff payload with reason `complaint`.
- Chit-chat "thanks!" → template reply, zero LLM calls.

## Out of scope
Knowledge path (11), refund path (12).

## Done when
- [ ] A manual run (`scripts/chat_cli.py`, add it: a tiny REPL over `build_graph`) can answer "where is my order 1042?" for a seeded customer
- [ ] `make check` green; PROGRESS row 10 updated
- [ ] Interview note `docs/notes/10-tool-paths.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(graph): order-tool ReAct path with step cap, complaint and fixed-reply paths, shared handoff payload
```
