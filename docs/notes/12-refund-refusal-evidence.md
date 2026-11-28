# 12 — Evidence for the refusal check and the refusal rule

**What**
I re-scored the earlier v4 runs with the new refusal rule. Then I ran dev and test again with the code check. All runs used the same scoring, so each change shows on its own.

**Why**
Two changes landed together: a scoring rule and an agent check. Scoring old and new chats the same way separates their effects. Each fix had a target scenario to watch.

**Number**
On dev, task success rose from 88.89% to 96.30% with the check. The final-sale scenario went from none to three of three. No run created an unexpected refund.

Source: eval/reports/refund_12g_dev.md

**Trade-off**
Two other scenarios got worse in this run. Their failing chats never reached the refund decision. One was intent misclassification, the other a missing order number.

**Likely follow-up question**
Q: How do you know the check did not cause those drops?
A: I read every failing chat. None of them reached the step the check changes.
