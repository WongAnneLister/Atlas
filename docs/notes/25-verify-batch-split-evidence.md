# 25 — Evidence for the claim-check split

**What**
I ran the full graph on dev and test after the split fix. I compared both with the same settings before the fix. I added the runs to the regression report.

**Why**
The fix changes how many checker calls a long answer makes. I had to show it removes the overflow handoffs. I also had to show it does not change other results.

**Number**
No answer hit the overflow error on dev or test. The split happened on one dev question out of 150. Dev false rejects went from 14 to 11 of 120, which is not significant. Test stayed at 15 of 120, with no false accepts.
Source: eval/reports/context_regression.md

**Trade-off**
The overflow was rare, so the measured gain is small. One run cannot prove the split never changes a verdict. The offline tests check that each claim still gets exactly one verdict.

**Likely follow-up question**
Q: How do you know the split did not hide a bad claim?
A: Each smaller call still needs a verdict and a real quote for every claim. A missing or invalid verdict still hands off. So splitting only changes batch size, not the bar.
