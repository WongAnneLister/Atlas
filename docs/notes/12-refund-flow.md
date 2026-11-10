# 12 — Refund / return sub-flow with interrupt and resume

**What**
I built a refund flow that verifies the customer order before any decision.
I added an order picker interrupt for requests without a clear order id.
I retrieve policy evidence, run the evidence gate, and store the decision.

**Why**
Refund answers need both trusted order facts and current policy text.
Without this flow, the agent could guess eligibility or use another customer’s order.
The picker also lets a user continue safely across graph requests.

**Number**
No number yet. I will measure it in commit 13.
Source: eval/reports/

**Trade-off**
The flow adds retrieval, checks, and a possible human handoff.
That costs time for uncertain requests, but it prevents unsafe refund approvals.
Requests stay pending review, so this commit does not move money.

**Likely follow-up question**
Q: How do you stop the model from approving a final-sale item?
A: Code checks the item ids, citations, and final-sale policy text.
If any check fails, the decision becomes needs_human.
