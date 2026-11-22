# 23 — Selecting the policy in force

**What**
I added dates to policy sections and their search records.
I use today's policy for general questions.
For refunds, I use the purchase date from the order record.
I show a dated notice when a reply cites an old policy.

**Why**
Return rules can change between a purchase and a refund request.
I wanted both kinds of search to see the policy that applies.
I use the stored order date even if the customer gives a different date.

**Number**
No number yet. I will measure it in commit 23b.

**Trade-off**
I need a full index rebuild to add the new fields.
Older indexes still serve their current policy text during rollout.
A dated search with no matching evidence goes to a human.

**Likely follow-up question**
Q: Why filter before ranking the results?
A: I want the ranker to compare only evidence that applies.
In the release check, I reuse scores for repeated question and passage pairs.
