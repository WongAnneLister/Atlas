# 12 — A status counts only when the policy speaks of orders in it

**What**
The refund check now looks for phrases like "cancelled orders" or "order has been shipped". A bare status word no longer counts. Ten example sentences pin the rule in tests.

**Why**
A paid order was refused because the cited text said "the amount paid". The old check saw the word "paid". It took that as a rule about paid orders. That refusal should have gone to a human.

**Number**
No number yet. I will measure it in the refund decision run that follows.

**Trade-off**
Unusual status wording in a policy now sends the case to a human. That costs agent time. It never lets a refund through by mistake.

**Likely follow-up question**
Q: Why not ask the model whether the policy covers the status?
A: This check exists to catch the model's mistakes. A rule in code cannot be argued with. The phrase list is short and tested.
