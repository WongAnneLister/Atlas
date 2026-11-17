# 16b — Refund decision prompt and window check

**What**
I made the refund decision step reach real, cited decisions.
I added short field descriptions to the decision schema, the format the model must fill.
They ask for a source number at the end of every reason.
I also added a code check that blocks approvals outside the return window.

**Why**
The model put all citations in a separate list, not inside its reasons.
My check needs a citation in each reason, so every decision went to a human.
After that fix, the model approved orders 35 days after purchase.
The policy allows only 30 days.

**Number**
I ran 14 named orders twice each.
Final decisions rose from 0 of 28 to 19 of 28.
On 20 other delivered orders, they rose from 0 of 20 to 13 of 20.
Wrong final approvals were 0 in every version after the window check.
Source: eval/reports/refund_decisions.md

**Trade-off**
The sets are small, and I wrote the expected answers myself.
I added the window check after seeing errors, so that holdout is no longer fresh.
Some orders still get a wrong "no", and code does not block those.
Code checks also send some correct decisions to a human.

**Likely follow-up question**
Q: Why not just tell the model to count days from purchase?
A: I tried that in a third prompt version, and it changed nothing.
The model kept counting from delivery and approved late orders.
Counting days is easy for code and risky for a model, so code does it.
