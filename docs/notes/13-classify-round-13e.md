# 13 — Three routing rules for common classifier mistakes

**What**
I added three lines to the classifier prompt. A question about whether one may return an item is a policy question. A reported account problem is an unsupported account request. Tracking a refund is a refund request.

**Why**
These were the classifier's three biggest error types on the reviewed holdout. Each line names a boundary the old prompt left vague.

**Number**
No number yet. I will measure it in the routing runs that follow.

**Trade-off**
Every prompt line can move other questions too. The routing dev set and the controls guard against that. The refund runs and the release gate guard the paths behind them.

**Likely follow-up question**
Q: Why is "Can I return this?" a policy question?
A: The customer asks whether it is allowed, not for the return itself. The policy answer comes first.
