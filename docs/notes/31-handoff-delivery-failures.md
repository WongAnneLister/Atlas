# 31 — Handoffs that never reach a person

**What**
I stopped hiding failures around the human handoff. If the queue rejects a handoff, the bot logs an error with the trace id. The turn also gets a flag called `handoff_delivery_failed`. The same happens when a message in human mode is not delivered.

**Why**
Before, these errors were silently ignored. The customer was told a person would reply. But nobody would ever see the ticket. Without a log line, an operator would never know.

**Number**
No number yet. I will measure it in the next handoff loop report.

**Trade-off**
The customer message stays the same for now. A clearer message would need a new template and a test. I kept this fix small, so it only makes the failure visible.

**Likely follow-up question**
Q: Why not retry the enqueue?
A: A retry inside the graph would delay the customer's reply. I chose to log and flag it first, so an alert can fire. The enqueue already carries an idempotency key. So a safe retry is a good next step.
