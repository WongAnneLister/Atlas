# Commit 12 — Refund / return sub-flow with interrupt and resume

**Week 3 · depends on: 10, 11**

## Context
`refund_request` and `return_exchange` follow a fixed sub-flow:
**identify order → (if unclear, pause and let the user pick) → read order facts → retrieve the relevant policy → gate → decide → create a refund request or hand off.**
Facts about the order come only from `OrderService`; the rules come only from retrieved policy text. The model's job is to
compare the two and explain — not to invent either.

## Read first
- `AGENTS.md` §5.2, §6
- `docs/ORDERS.md` (edge-case orders), `graph/tools.py`, `graph/nodes/knowledge.py`, `gate/evidence.py`
- LangGraph docs for `interrupt()` and resuming with `Command(resume=...)` in the installed version

## Task
1. `src/support_agent/graph/nodes/refund/` sub-graph (or a set of nodes) :
   - `identify_order` — extract an order id from the message/history with a regex first, then the `fast` model if needed. If found → verify ownership via `OrderService`. If none or not found → `list_recent_orders` and call **`interrupt({"type": "order_picker", "orders": [...]})`**. The resume value is the chosen order id (or `"none"` → handoff `order_not_found`).
   - `load_order` — put order facts into `order_context` (dates, status, items, final_sale flags, coupon, days since delivery relative to config "today").
   - `retrieve_policy` — build a policy query from intent + item categories + flags (e.g. "refund window for electronics, final sale items, coupon refunds"), run `hybrid_rerank`, then the **same** `gate.evaluate`. Gate fail → handoff `low_evidence`.
   - `decide` — `main` model with structured output `{eligible: yes|no|needs_human, items: [...], reasons: [...], citations: [...]}`. Prompt `graph/prompts/refund_decide.md`: use only order facts + numbered policy sources; any uncertainty → `needs_human`.
     Then **code checks** the decision: every reason must cite a source; if the model says `yes` but an item is `final_sale` and no cited source mentions final sale → force `needs_human`. Add a rule list in code for such cross-checks (small, documented).
   - `act` — `yes` → `OrderService.create_refund_request` (status `pending_review`; nothing is paid out) and a reply with the request id and citations. `no` → explain with citations and offer a human. `needs_human` → handoff `policy_requires_human`.
2. Wire path C in `build.py`. The checkpointer must persist the interrupt across HTTP requests later (thread id = conversation id).
3. `scripts/chat_cli.py` — support the order-picker interrupt (print the list, read the choice, resume).
4. `docs/REFUND_FLOW.md` — a small Mermaid diagram of the sub-flow, the cross-check rules, and a table of the edge-case orders from `docs/ORDERS.md` with the expected outcome.

## Requirements
- No refund is created without: a verified order owned by the customer, a passed gate, and a `yes` that survived the code checks.
- All decision outputs are stored in state for tracing and eval.

## Tests (fakes only)
- No order id → interrupt with the customer's recent orders; resume with an id → continues to `decide`.
- Resume with `"none"` → handoff `order_not_found`.
- Other customer's order id → treated as not found (no leak).
- Gate fail on the policy → handoff, zero calls to the decide model.
- Model says `yes` for a final-sale item without a supporting citation → `needs_human`.
- `yes` path creates exactly one refund request; `no` path creates none.
- Table-driven test over the edge-case orders using a fake decide model that returns the expected label, checking the code checks and the final action.

## Out of scope
Real payments. Memory (29, 30).

## Done when
- [ ] In `chat_cli.py`: "I want a refund for my last order" → picker → choose → cited decision
- [ ] `make check` green; PROGRESS row 12 updated
- [ ] Interview note `docs/notes/12-refund-flow.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(refund): refund/return sub-flow with order-picker interrupt, gated policy retrieval and code-checked decisions
```
