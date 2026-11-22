# 25 — Running the verifier on the claim set

**What**
I added a command that runs the live claim checks over the frozen claim set. It saves one verdict per claim and a reason for each.

**Why**
The scoring command needed predictions, but nothing produced them. Saved verdicts also let me rescore later when the author changes labels. That needs no new model calls.

**Number**
No number yet. I will measure it in commit 25b.

**Trade-off**
I verify one claim per call. The live check sends a whole answer at once. A batch can change how the model judges. A failed call counts as unsupported, because the live check then withholds the answer.

**Likely follow-up question**
Q: Why not batch claims like the live check?
A: Single calls keep each verdict independent and easy to rescore. The end-to-end runs still measure the live batched check.
