# 27 — Simulator runs that refuse to report a broken model

**What**
Each simulated turn now records the first model or dependency error the agent hit. A sim run or replay with too many such chats writes no report. The replay tool also makes one tiny call per model before it starts.

**Why**
My first live replay ran while the model account ran out of money. Half the turns failed, and the agent fell back to template replies. The replay still wrote a normal-looking report.

**Number**
No number yet. I will measure it in the replay run that follows.

**Trade-off**
A short outage now voids a whole run, so it must be collected again. The preflight call costs a few tokens. Both are cheaper than a report built on failed calls.

**Likely follow-up question**
Q: Why did the full-graph evals already catch this?
A: I added the same guard there earlier, after a missing package broke a run. The simulator tools were added later and missed it. They now use the same rule.
