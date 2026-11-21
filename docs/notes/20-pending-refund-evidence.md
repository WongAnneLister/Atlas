# 20c — Red-team rerun after the refund fix

**What**
I reran the red-team test split on the fixed code.
I used the same cases, model and settings as the baseline.
Then I compared each case with its baseline result.

**Why**
A fix needs a before and after number.
Without the rerun, I could not show the gap was closed.
I also needed to check that nothing else got worse.

**Number**
Attacks succeeded in 0 of 65 cases.
Refund fraud went from 3/10 in the baseline to 0/10.
The same three repeat requests now go to a human.
No other case got worse.
Source: eval/reports/redteam.md

**Trade-off**
Ten cases per category is a small sample.
A score of 0/10 still allows a real rate near 28%.
I did not run a significance test on this change.
So the strong proof is the tests, not this rate.

**Likely follow-up question**
Q: Does 0/65 mean the agent is safe?
A: No, it means these 65 attacks failed.
The cases come from a few templates, so they overlap.
New attack styles could still work.
Commit 21 adds guardrails and sets budgets on this set.
