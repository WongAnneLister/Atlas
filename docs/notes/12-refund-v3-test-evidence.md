# 12 — Test results after adopting the v3 refund prompt

**What**
I ran the nine test refund scenarios once with v3. I compared them with the earlier v2 run, both scored by the current labels. I also ran the release gate with red-team attacks.

**Why**
A new decision prompt can approve refunds it should not. The red-team set includes refund fraud attempts. I had to check that v3 still blocks them.

**Number**
Task success was 77.78% with v2 and 74.07% with v3. The intervals overlap, and neither run created an unexpected refund.

Source: eval/reports/refund_v3_test.md

**Trade-off**
v3 did not fix the scenario it was meant to fix on test. The model treats an old policy as expired. It does so even for orders bought under it. That needs one more prompt change.

**Likely follow-up question**
Q: Why keep v3 if test did not improve?
A: The decision was made on dev, before test ran. Test only reports. Safety held, so I keep v3 and fix the date rule next.
