# 12 — The v3 refund prompt is now the default

**What**
I switched the refund decision prompt from v2 to v3. The same rule I wrote before the trial now passes. A test pins the shipped setting.

**Why**
v2 sent in-window orders to a human when any retrieved window was exceeded. v3 counts each window from the date the policy names. With the reviewed labels, v3 met every condition of the rule.

**Number**
No number yet. I will measure it in the test and red-team runs that follow.

**Trade-off**
The rule passed only after I fixed four labels. I fixed them from the policy text, in a separate commit. v3 still refuses a final-sale order that I expect to go to a human.

**Likely follow-up question**
Q: Is it fair to re-apply the rule after changing labels?
A: The rule did not change, only labels that contradicted each other. I re-scored the same saved chats. Test then runs once, after the decision.
