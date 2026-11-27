# 12 — Evidence for the refund fixes

**What**
I ran all nine test refund scenarios three times each, before and after the fixes. Both runs used the same index and clean order data. I scored both runs with the same current rules.

**Why**
Three changes landed together. They were an agent check, clean order data and a scoring rule. Scoring both runs with one rule separates the scoring change from the rest.

**Number**
Task success rose from 37.04% to 77.78% over 27 chats. The intervals do not overlap. Both runs were scored with the same current rules.

Source: eval/reports/refund_sim.md

**Trade-off**
Each scenario has only three chats, so per-scenario counts are rough. One eligible scenario still fails on a return-window check. Two refusals still fail at the policy evidence gate.

**Likely follow-up question**
Q: How much of the gain is just the new scoring rule?
A: Six of the 27 chats. The rest comes from the status check and clean order data.
