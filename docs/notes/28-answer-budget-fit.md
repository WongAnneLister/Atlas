# 28 — The answer prompt fits its token budget

**What**
The answer step now drops its lowest-ranked sources until the prompt fits its token budget. Each question part keeps at least one source. If one source alone is too big, the turn hands off with a context-overflow reason. A config switch turns this off, only for measuring it.

**Why**
A few catalog chunks hold a whole product manual. One long chat sent a 46460-token answer prompt against a 12000 budget. The claim check then overflowed, and the turn handed off after a costly call.

**Number**
No number yet. I will measure it in the replay that follows.

**Trade-off**
A dropped source is one the model can no longer cite. The rule drops the lowest-ranked one first, like the builder does. The real cause, unsplit manuals in the index, still needs its own fix.

**Likely follow-up question**
Q: Why not split the big chunks instead?
A: That is the real fix. But it needs a new index and a full release check. This change stops the over-budget call today. It also protects against any future oversized chunk.
