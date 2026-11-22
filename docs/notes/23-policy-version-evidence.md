# 23b — Policy version evidence

**What**
I rebuilt the index with dated policy sections and released it through the paired check. Then I measured old and new policy versions with and without the date filter. I also ran the refund path end to end with real models. Then I ran the red-team set and the integration tests.

**Why**
Commit 23 added policy versions, but only fakes had tested them. Without real numbers I could not say the filter picks the right version. I also had to show that the old eval_v1 results did not get worse.

**Number**
Without the filter, all 24 test questions had the wrong version in the top 5. With the date filter, none of the 24 did. End to end, no refund reply cited the wrong version, 0 of 16. The eval_v1 release check stayed identical, and red-team attacks stayed at 0 of 73.
Source: eval/reports/policy_versions.md

**Trade-off**
The versions are synthetic: two sections and one change date. The test set is small, so the intervals are wide. The gate still rejects all 20 dated knowledge questions, because of an old word rule. I report that miss instead of tuning the gate here.

**Likely follow-up question**
Q: What if the customer gives a different purchase date?
A: The filter always used the stored order date, 16 of 16 times. But the decision model changed its answer on 4 of 8 orders. It never approved wrongly, and I will make the prompt trust the stored date.
