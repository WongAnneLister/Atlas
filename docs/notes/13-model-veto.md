# 13 — A missing model number now blocks the answer

**What**
I added a stricter veto to the evidence gate. If a question names model numbers, one must appear in the top chunks. Other names, like "USB", no longer count instead. The gate is my check that evidence is strong enough to answer.

**Why**
A question asked about TAH5206 headphones, which my documents do not cover. The old veto passed because "USB" matched the TAH6206 manual. Then only the model's coverage check stood in the way, and it slipped once.

**Number**
At gate level, exactly two no-answer questions flipped to blocked. No answerable question changed in any set. The dev threshold stayed the same on both indexes. In the full run, all 30 model-number dev questions still passed the gate.
Source: eval/reports/model_veto.md

**Trade-off**
One named model is enough to pass. So "X rather than Y" still works. A question about two models, one unknown, also passes. I kept that, because blocking it would reject real correction questions.

**Likely follow-up question**
Q: Why not ask for every model number to match?
A: Customers often name a model to exclude it. Requiring all models would reject those. The coverage check still catches a missing second model later.
