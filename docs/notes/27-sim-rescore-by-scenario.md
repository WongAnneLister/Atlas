# 27 — Re-scoring shows task success per scenario

**What**
The re-scoring tool can now add a table of task successes per scenario. Each saved run gets its own column. No model is called.

**Why**
I changed a scoring rule and an agent check in the same fix. A per-scenario table scores old and new chats with the same rule. That separates the agent's change from the scoring change.

**Number**
No number yet. I will measure it in the refund evidence that follows.

**Trade-off**
Per-scenario counts are tiny, often three chats each. They show where things changed, not how sure we can be. The overall rate still carries the interval.

**Likely follow-up question**
Q: Why re-score old chats instead of rerunning them?
A: Rerunning adds model noise to the comparison. Re-scoring the same chats isolates the rule change exactly.
