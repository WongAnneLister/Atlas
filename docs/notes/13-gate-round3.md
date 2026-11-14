# 13 — Evidence gate round three

**What**
I fixed a free score in the evidence gate. Questions without key terms no longer get key_hit points. Names like "Cash App Pay" now count as key terms. If no asked-about name is in the top results, the gate hands off.

**Why**
The old gate gave every unanswerable question 0.15 for free. The threshold sat only 0.0018 above the worst dev no-answer score. A related payment page let Cash App Pay through.

**Number**
On the new holdout, the gate let through 55/106 instead of 81/106. The full system still answered 13/106 both before and after. Eight of those used Flipkart facts for generic-store questions.
Source: eval/reports/gate_round3.md

**Trade-off**
Two answerable old test questions now hand off at the gate. More questions stop early, so fewer model calls run. The final false accept count did not move. I report that miss openly.

**Likely follow-up question**
Q: Why did the full count not drop?
A: The remaining misses are not weak retrieval. The search finds strong text from the wrong store. A score cannot see that. I need a code check on the store of each cited source.
