# 13 — Routing checks for the next classifier round

**What**
I wrote six new routing checks and the adoption rule before changing the classifier. They cover permission questions about returns, account problems, and refund tracking. I wrote them fresh, not copied from the intent holdout.

**Why**
The reviewed holdout showed these three error types. But the holdout must stay a fair test, so I cannot tune on it. The routing checks give me a separate place to measure the fix.

**Number**
No number yet. I will measure it in the routing runs that follow.

**Trade-off**
Six hand-written checks are thin evidence. They catch a broken rule, not a small drift. The holdout reports the real effect once, at the end.

**Likely follow-up question**
Q: Did you peek at the holdout to write these?
A: I knew the error types from the holdout, but not by copying items. Each check uses new wording and new products.
