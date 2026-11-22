# 24 — Evidence for every requested fact

**What**
I restored the rule that every requested fact needs evidence from that part's sources.
I added checks for that line and the multipart input and output instructions.

**Why**
One planned part can still ask for several facts.
Without this rule, the model could treat evidence for one fact as enough.

**Number**
No number yet. I will measure it in commit 24b.

**Trade-off**
The prompt now spells out the evidence requirement for questions with several facts.
The test protects the wording. Live evaluation checks whether the model follows it.

**Likely follow-up question**
Q: Can a part borrow evidence from another part?
A: Each part gets its own list of sources.
The graph checks each quote against the sources for that part.
