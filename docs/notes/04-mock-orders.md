# 04 — Mock orders and an ownership-checked service

**What**
I added demo orders and a small order service. I checked each order's owner before reads or writes. Refund calls only create requests for human review.

**Why**
Public datasets do not contain the orders my demo needs. Fixed dates and a fixed seed keep those facts repeatable. Owner checks prevent customers from accessing another customer's order.

**Number**
I seeded 300 orders for 50 fake customers. The audit blocked 900 attempts to access another customer's orders. I covered 14 named edge cases.
Source: eval/reports/archive/orders_seed-5fbeb90.md

**Trade-off**
I chose SQLite, a small database stored in a local file. That keeps the demo easy to run. It does not model a real payment system. Prices are made up even when products come from the catalog.

**Likely follow-up question**
Q: How did you prevent one customer from seeing another customer's order?
A: I included the customer id in every order lookup. Missing orders and foreign orders return the same error. I also checked each refund item's order before saving the request.
