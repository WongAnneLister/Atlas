# 28 — Answer prompt back to the old layout

**What**
I set the answer node to the layout from before the context builder. It now gets only its task prompt and its input. Every other node keeps the builder. I chose this with a rule I wrote down before the dev runs.

**Why**
After the builder, test false rejects rose. On dev, the old and new answer layouts tied. My rule said a tie keeps the old prompt. The evidence gate and claim checks were tuned on that prompt.

**Number**
No number yet. I will measure it in the evidence commit that follows.

**Trade-off**
The answer call no longer shares the cached prefix. It also no longer sees pinned facts or customer memory. Memory is never evidence for a cited answer, so I accept that.

**Likely follow-up question**
Q: Isn't a tie a weak reason to change the default?
A: Yes, it is weak evidence. But the new prompt was never measured before it shipped. So the change had to earn its place, and on dev it did not.
