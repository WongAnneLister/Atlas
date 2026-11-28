# 13 — Evidence for the three new classifier rules

**What**
I tested the three new prompt lines against a rule I wrote first. I ran the routing dev questions and controls before and after. I also ran the dev refund scenarios and the release gate. Then I reported the intent holdout once.

**Why**
A prompt line can quietly move other questions to the wrong path. The rule had to judge the change without the holdout. The holdout already told me which errors to fix.

**Number**
Intent accuracy rose to 0.9119, which is 383 of 420. The confidence interval runs from 88.10% to 93.81%. So the lower bound is still below the 90% target.

Source: eval/reports/intent.md

**Trade-off**
The holdout picked the error types, so it is not fully independent now. One dev question moved to the complaint path by mistake. Three refund-update questions now disagree with my own labels.

**Likely follow-up question**
Q: Did you tune the prompt on the holdout?
A: The holdout chose the topics, not the wording. I checked the wording only on dev questions and controls.
