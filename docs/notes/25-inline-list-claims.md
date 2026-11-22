# 25 — Claims from inline numbered lists

**What**
I fixed how answers with inline numbered steps split into claims. Each step now becomes its own claim. The next step's number no longer sticks to the end of the previous claim.

**Why**
While building the claim set, 19 of 350 claims ended with a stray step number. A reviewer cannot label "Choose the item 3." cleanly. The live check splits answers the same way, so its claims were broken too.

**Number**
No number yet. I will measure it in commit 25b.

**Trade-off**
The rule needs steps 1 and 2 in order before it sees a list. So a single "40." in a sentence is left alone. A list that starts at another number is not split.

**Likely follow-up question**
Q: Why fix this before labelling?
A: Labels are tied to the exact claim text. A later splitter change would make old labels point at different claims.
