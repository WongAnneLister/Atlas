# 12 — The v4 refund prompt is now the default

**What**
I switched the refund decision prompt from v3 to v4. The rule I wrote before the runs passed on dev. A test pins the shipped setting.

**Why**
v4 says an old policy still covers orders placed while it was valid. Without that, an in-window order went to a human. Safety had to hold before I switched.

**Number**
On dev, task success was 81.48% for both versions, with no unexpected refund. So the rule passed on a tie.

Source: eval/reports/refund_v4_dev.md

**Trade-off**
Dev cannot show the gain, because no dev scenario hits this case. The evidence for the fix will come from one test run. That is weaker than a dev win.

**Likely follow-up question**
Q: Why adopt a change that did not move dev?
A: The rule allowed a tie, and safety held. The change is one sentence about dates. Test then shows whether it fixes the case.
