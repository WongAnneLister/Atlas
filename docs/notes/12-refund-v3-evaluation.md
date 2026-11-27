# 12 — The v3 refund prompt was not adopted

**What**
I tested the v3 refund decision prompt against v2 on the dev refund scenarios. I wrote the adoption rule before the runs. The rule failed, so v2 stays the default.

**Why**
v2 wrongly sends some in-window orders to a human, because of a return-window check. v3 counts the window from the date the policy names. I needed dev evidence before switching.

**Number**
Task success was 51.85% with v2 and 55.56% with v3. Both versions created refunds where the scenario expected a human. That broke the rule for v3.

Source: eval/reports/archive/refund_v3_dev-b44b217.md

**Trade-off**
v2 keeps its known window mistake for now. The real blocker is a label conflict. Two eval sets expect different outcomes for the same orders.

**Likely follow-up question**
Q: Why not just fix the labels and adopt v3?
A: Labels are the author's call, and I saw the results first. Fixing them needs a separate, reasoned review. Then the rule can run again.
