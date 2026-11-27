# 28 — Evidence for the answer-budget fit

**What**
I measured the budget fit three ways. Saved eval rows showed which items it could touch. I ran the one flagged test item live, with the fit on and off. I also replayed the long chat turn that first showed the bug.

**Why**
A fix that drops sources could hurt answers. I needed to show where it acts and what it changes there. Most items never reach the budget, so they cannot change.

**Number**
In the replay, the answer prompt reached 47642 tokens with the fit off. With it on, the largest prompt was 11950 tokens and nothing overflowed. But all 5 turns still handed off in both arms.

Source: eval/reports/answer_budget_replay.md

**Trade-off**
The fix cuts cost and removes an error. It does not make that long turn answerable. Three of its handoffs now come from invalid answer output. I have not examined why yet.

**Likely follow-up question**
Q: So did the fix help the customer at all?
A: Not on that turn. It stopped a very large wasted call and an overflow in the claim check. The flagged eval item still answered, with far fewer tokens.
