# 25 — Split claim checks that exceed the budget

**What**
I changed how the claim checker handles a large batch. Over the token budget, it now halves the batch until each half fits. One claim that is still too large hands off, as before.

**Why**
Each claim carries the full text of the sources it cites. An answer with many claims could exceed the budget. Then the whole answer went to a person, even when every claim was fine.

**Number**
No number yet. I will measure it in the regression run that follows.

**Trade-off**
A split batch makes more model calls. That adds cost and latency, but only for the rare large answer. The verdicts should not change, because each claim is checked only against its own sources.

**Likely follow-up question**
Q: Why not just raise the budget?
A: A bigger budget only moves the limit. Splitting keeps the cost guard and still checks every claim. I measured the checker on one claim per call, so smaller batches match that.
