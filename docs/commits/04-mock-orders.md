# Commit 04 — Mock orders and OrderService

**Week 1 · depends on: 01 (can run in parallel with 02/03)**

## Context
Public datasets have no orders, but the order/shipping path and the refund sub-flow need them.
We generate a few hundred fake orders from a fixed seed and expose them through a small service the agent's tools will call.

## Read first
- `AGENTS.md` §5.2, §5.3, §6 (paths A and C)
- `configs/default.yaml` → `orders`

## Task
1. `src/support_agent/orders/models.py` — Pydantic models: `Customer`, `Order`, `OrderItem`, `Shipment`, `RefundRequest`.
   Order status enum: `pending, paid, shipped, in_transit, delivered, cancelled, refunded, partially_refunded`.
   Fields needed by refund rules: `order_date`, `delivered_at`, `total`, `paid_with_coupon` (bool + coupon code), `items[].final_sale` (bool), `items[].category`.
2. `src/support_agent/orders/db.py` — SQLite schema + repository (stdlib `sqlite3`, no ORM). DB path from config.
3. `src/support_agent/orders/seed.py` + `make data-orders`:
   - Fixed seed from config. ~50 customers, ~300 orders, 1–4 items each. Use products from `data/processed/catalog/products.jsonl` if it exists, else a built-in small product list.
   - Cover every status and the edge cases refunds need: delivered 5 / 29 / 31 / 90 days ago, final-sale items, coupon orders, partially refunded, cancelled, in-transit with delayed tracking.
   - Emails use `@example.com`. Dates are relative to a fixed "today" in config so evals are stable.
4. `src/support_agent/orders/service.py` — `OrderService` with:
   `get_order(order_id, customer_id)`, `list_recent_orders(customer_id, limit=5)`, `get_tracking(order_id, customer_id)`, `create_refund_request(order_id, customer_id, item_ids, reason) -> RefundRequest` (writes a row with status `pending_review`; it never moves money).
   Every method checks the order belongs to the customer → otherwise raises `OrderNotFound` (do not leak existence).
5. `docs/ORDERS.md` — schema, edge-case table (which order ids cover which case), and how to reseed.

## Requirements
- `make data-orders` is idempotent (drops and recreates the DB).
- The `.sqlite` file is gitignored.
- The service is synchronous and pure Python; tools in commit 10 will wrap it.

## Tests
- Seed is deterministic (two runs → same order ids and totals).
- Every edge case in `docs/ORDERS.md` exists after seeding.
- Ownership check: customer A cannot read customer B's order.
- `create_refund_request` does not change order status.

## Out of scope
Refund eligibility rules (commit 12 — they come from policy docs + retrieval, not hard-coded here). LangChain tools (commit 10).

## Done when
- [ ] `make data-orders` creates the DB; `docs/ORDERS.md` lists the edge-case orders
- [ ] `make check` green; PROGRESS row 04 updated
- [ ] **Checkpoint 1**: if 02, 03, 04 are all done, mark "Week 1 gate passed" in PROGRESS
- [ ] Interview note `docs/notes/04-mock-orders.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(orders): seeded mock order database and ownership-checked OrderService
```
