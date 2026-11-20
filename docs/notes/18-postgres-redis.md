# 18 — PostgreSQL, Redis, and saved chat progress

**What**
I moved orders and saved chat steps to PostgreSQL, a shared database.
I added Redis, a service for short-lived data.
I added health checks for both stores and the search service.

**Why**
A restart could erase the chat while a customer was choosing an order.
I saved the chat so another process could continue the refund.
I used the saved message ID to keep a repeated write from creating another request.

**Number**
I compared 300 orders across 50 customers on both databases.
I found 0 mismatches in the seeded records.
Source: eval/reports/orders_parity.md

**Trade-off**
I added more services to run and check in production.
I kept SQLite and in-memory chat state for local development.
I accepted the extra setup so workers could share saved chat progress.

**Likely follow-up question**
Q: How did you check that a refund could continue after a restart?
A: I sent a refund question to the API and got an order picker.
I stopped the API and started it again.
I sent the selected order and saw the refund request saved for review.
