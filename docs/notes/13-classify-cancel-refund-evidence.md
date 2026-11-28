# 13 — Evidence for routing "cancel and refund" to refunds

**What**
I compared the classifier prompt before and after the new line. I used dev questions and routing checks. I also ran the dev and test refund scenarios. The rule was written before any run.

**Why**
A routing change can move other questions to the wrong path. I had to show that only the intended requests moved. The frozen intent set could not run, so I used the routing method.

**Number**
On the routing checks, the pass count rose from 23 to 25 of 25. Dev questions stayed at 119 of 120. Only the two new cancel-and-refund checks changed route.

Source: eval/reports/routing_12h.md

**Trade-off**
Three hand-written checks are a thin guard. The gain on the real case shows only on test. The frozen intent set stays stale until someone rebuilds it on purpose.

**Likely follow-up question**
Q: Did a plain cancel request start going to refunds?
A: No. Both cancel-only checks stayed on the order path.
