# 11 — Evidence gate and the knowledge path

**What**
I added an evidence check before the model writes knowledge answers.
Weak support now goes to a human.
Supported answers cite the chunks they use.

**Why**
Without this check, the model could answer questions the documents do not support.
That can turn missing evidence into a false policy claim.

**Number**
No number yet. I will measure it in commit 13.
The dev analysis could not run because Milvus was unavailable.

**Trade-off**
Some answerable questions may reach human support.
That costs staff time, but prevents answers with weak support.

**Likely follow-up question**
Q: How will you choose the gate threshold?
A: I kept the current value as an explicit demo placeholder.
I will compare thresholds on dev questions in commit 13.
I will report the selected threshold on held-out test questions.
