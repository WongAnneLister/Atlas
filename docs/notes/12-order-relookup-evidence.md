# 12 — Checking the order re-read fix

**What**
I ran the release gate, the red-team smoke test and the dev recall chats. I also checked whether the new reminder ever fired in those chats.

**Why**
The fix changes the order path, which guards customer data. I had to show it opens no new attack. I also wanted to see the fix work in a live chat.

**Number**
The gate passed with no false accepts in 30 no-answer questions. No red-team attack in the smoke set succeeded. The dev recall score was 100.00%, but the reminder never fired.
Source: eval/reports/sim_rescore.md
Source: eval/runs/order-relookup/gate.md

**Trade-off**
So the higher recall score is just run-to-run variation. The bug appeared on only two turns in one earlier run. I need a replay of that exact chat to measure the fix live.

**Likely follow-up question**
Q: Then how do you know the fix works?
A: Unit tests replay the exact model behaviour: a reply with no lookup. They fail without the fix and pass with it. The live effect is still unmeasured, and I say so.
