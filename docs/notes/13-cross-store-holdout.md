# 13 — A fresh cross-store holdout

**What**
I wrote 35 new questions that name one store. Each asks for a fact only the other store has. I froze them before writing the fix they will judge.

**Why**
My last test showed a clear leak. The bot used Flipkart rules to answer generic-store questions. I had already seen those test items. A fix needs questions I have not tuned on.

**Number**
The build report lists 35 frozen items. There are 22 generic-store items and 13 Flipkart items. I have not measured the bot on them yet.
Source: eval/reports/holdout_near_miss_v2.md

**Trade-off**
The set is small, so one miss moves the rate a lot. I wrote the questions after I knew the failure. They may match my fix better than real traffic does.

**Likely follow-up question**
Q: Why freeze questions before writing the fix?
A: It stops me from bending the test toward my code. The commit order proves which came first. Anyone can check that in the history.
