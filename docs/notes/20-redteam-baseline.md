# 20a — First red-team numbers

**What**
I ran the red-team test split on the clean commit 20 code.
A red-team set is a group of attacks on my own agent.
I used the official DeepSeek API with one model for every role.

**Why**
Commit 21 adds defences, and it needs a "before" number.
Without one, I cannot show that a defence helped.

**Number**
Attacks succeeded in 3 of 64 cases, about 5 percent.
All three were repeat refund requests on one order.
One more case failed on a retrieval outage.
Source: eval/runs/redteam-test-20261121-4595ec9b-e671eb1e/metrics.json

**Trade-off**
Each category has only 8 to 10 cases, so the error bars are wide.
A zero can still hide a real rate near 30 percent.
The policy judge never ran, because no reply made a promise to judge.

**Likely follow-up question**
Q: Why did the repeat refund attack work?
A: The refund step never reads earlier requests for the order.
So it opens a second request for human review.
I will fix that in commit 21 and rerun this set.
