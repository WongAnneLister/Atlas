# 25 — Several quotes per verified claim

**What**
I let the verifier give several short quotes for one claim. Code checks each quote against the claim's own source. I also told the prompt never to join passages with "...".

**Why**
On dev, the verifier removed 4 true product claims. Each claim stated several facts. The model joined fragments with "..." into one quote. Code could not find that quote in the source.

**Number**
No number yet. I will measure it in commit 25b.

**Trade-off**
I changed the verifier after looking at dev results, which is what dev is for. I did not tune it to my own draft labels. That would make the check grade itself.

**Likely follow-up question**
Q: Is one long quote not simpler?
A: Product facts sit far apart in a spec sheet. One exact quote per fact is shorter and easier to check.
