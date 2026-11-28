# 12 — Test results for the v4 refund prompt

**What**
I ran the nine test refund scenarios once with v4. I compared them with the v3 test run, under the same labels. I also ran the release gate with red-team attacks.

**Why**
Dev could not show the fix, because no dev scenario hits this case. Test was the only place to see it. Safety still had to hold.

**Number**
Task success rose from 74.07% to 85.19%. The intervals overlap, and no run created an unexpected refund.

Source: eval/reports/refund_v4_test.md

**Trade-off**
The case behind the fix passed two of three runs, not all three. The gain rests on one test run. One refusal scenario still fails after a request for an exception.

**Likely follow-up question**
Q: Is this gain real or just noise?
A: The intervals overlap, so I cannot claim it overall. The scenario it targets went from none to two of three.
