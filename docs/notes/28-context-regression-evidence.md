# 28 — Context regression evidence

**What**
I measured the agent after ten new commits against the last checked version. I found a test regression, then compared three answer layouts on dev. I ran test once for the chosen layout. I also ran the release gate and red-team smoke again.

**Why**
The context builder changed every prompt. But no core quality eval ran after it. Without that check, a worse answer rate would ship unseen.

**Number**
After the new commits, test false rejects rose from 16 to 24 of 120. On dev, the three layouts tied at 11, 13 and 14 of 120. With the old answer layout, test false rejects were 15 of 120. False accepts stayed at 0 of 30 in every run.
Source: eval/reports/context_regression.md

**Trade-off**
Dev did not show the regression. So my fix is a written tie-break, not a proven gain. The test result may partly be model noise. I report it as one run, and I made no change from it.

**Likely follow-up question**
Q: Why not pick the layout with the best dev number?
A: The differences on dev were too small to mean anything. Picking the best of three noisy numbers would fit noise. So I wrote the rule before the runs and followed it.
