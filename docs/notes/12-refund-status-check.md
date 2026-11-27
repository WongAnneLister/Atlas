# 12 — Refund refusals need a rule for the order's status

**What**
A refund refusal now passes the same status check as an approval. If no cited rule names the order's status, the case goes to a human. If every open item already has a request in review, the agent says so.

**Why**
The model refused a cancelled order's refund with the 90-day return window. That rule is for delivered goods, not cancellations. The customer explained twice and got the same wrong refusal.

**Number**
No number yet. I will measure it in the refund evidence that follows.

**Trade-off**
More refund requests now go to a human. That costs agent time. A wrong refusal costs the customer money, which is worse.

**Likely follow-up question**
Q: Why not fix the prompt instead of adding a code check?
A: The prompt already says to use a human when no rule fits. The model still refused. A code check cannot be talked out of it.
