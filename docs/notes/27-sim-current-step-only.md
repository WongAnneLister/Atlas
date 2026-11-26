# 27 — Showing the simulated customer one step at a time

**What**
Scripted chats now show the simulated customer only the current step. Other turns get a short rule: ask a natural follow-up, nothing more. The recall turn itself must now be sent before the chat may end.

**Why**
On dev, the customer still saw the whole script and did later steps early. It asked for the recap on turn three, then just said thanks on turn four. An off-by-one also let the chat end right at the recall turn.

**Number**
No number yet. I will measure it in the dev rerun that follows.

**Trade-off**
The customer now knows less of its plan. Its messages may feel less natural. Filler turns add model calls. Unscripted scenarios still see their full hints, so their behaviour does not change.

**Likely follow-up question**
Q: Did you tune the simulator on the test scenarios?
A: No. I looked only at dev transcripts to find these problems. The test scenarios stay untouched for the report.
