# 12 — A refund refusal needs a reason code can confirm

**What**
A refusal for a delivered order now stands only if a return window has passed. A refusal of a final-sale item goes to a human. Every other refusal goes to a human too.

**Why**
The model once refused an order while writing that it was inside its 90-day window. It also refused final-sale items, which I decided should go to a human. The policy only says they are usually not returnable.

**Number**
No number yet. I will measure it in the refund runs that follow.

**Trade-off**
More refusals now go to a human, which costs agent time. A refusal for misuse or similar reasons also goes to a human. No extra refund can come from this check.

**Likely follow-up question**
Q: Why not trust the model's reasons?
A: Its reasons and its answer disagreed in one run. Code can check the window, so it checks it.
