# 13 — The intent holdout, re-measured with today's prompt

**What**
I rebuilt the frozen intent holdout with the current classifier prompt. The questions came out byte-identical. Then I measured intent accuracy again, once.

**Why**
The holdout had not run since I changed the classifier on November 11. Its loader refuses a changed prompt, so the old score described an old prompt. I needed a score for the prompt that actually ships.

**Number**
Intent accuracy is now 0.7048, below the 90% target. Most misses are how-to questions sent to the policy intent.

Source: eval/reports/archive/intent-1a7971a.md

**Trade-off**
The holdout labels follow topic, while my routing follows informational versus operational work. So the drop mostly measures that mismatch. I have not yet decided which convention the holdout should follow.

**Likely follow-up question**
Q: Did the classifier get worse, or did the test change?
A: Neither alone. The rule changed on purpose and the labels did not follow. I need to relabel or revise the rule.
