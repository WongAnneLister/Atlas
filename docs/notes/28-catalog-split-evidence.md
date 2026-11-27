# 28 — Evidence for splitting the catalog manuals

**What**
I collected before and after evidence for the new index, on the same code. The new index splits only catalog sections over 4096 tokens. I checked chunk sizes on both builds. I also replayed the long chat that first showed the bug.

**Why**
A new index changes what every question retrieves. My first split rule hurt ranking and was refused at release. So I needed to show that the second rule changes nothing it should not.

**Number**
The new build's largest chunk is 2989 tokens, and it passes the 4096 cap. The old build's largest chunk is 12331 tokens, and it fails.

Source: eval/reports/chunk_sizes.md

**Trade-off**
The long chat turn is still not answered. Its prompt now fits, but all ten replays hand off at the claim check. The released index lives only on my local copy so far.

**Likely follow-up question**
Q: If nothing changed in the evals, what did the split buy you?
A: Few eval items touch those manuals, so the evals barely move. The gain is that no chunk can overflow a prompt now. The build also fails if one ever does.
