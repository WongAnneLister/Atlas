# 22 — Build and release an index safely

**What**
I built a new search index whenever the policy documents change.
I copied unchanged vectors and encoded the changed sections.
I added a switch that can restore the previous index.

**Why**
I wanted to check new search results before customers use them.
I kept the previous index so I can recover quickly.

**Number**
No number yet. I will measure it in commit 22b.

**Trade-off**
A new index takes extra space during a release.
The release check also takes time on a CPU.
I accepted that cost to keep the live index intact.

**Likely follow-up question**
Q: What happens when I roll back and then edit a document?
A: I compare the edit with the sections in the serving index.
I use its saved section versions to choose what to encode.
