# 23 review — Require a filter capability check

**What**
I made dated search require a clear answer about filter support.
I updated the evaluation wrappers to pass that check to their search source.

**Why**
A missing check let a search mix older and current policies.
I wanted the search to stop before it could return that evidence.

**Number**
No number yet. I will measure it in commit 23b.

**Trade-off**
Each new wrapper has to pass through the check.
An old index can still serve its current policy text.
I record when that search runs without filters.

**Likely follow-up question**
Q: How do I tell an old index from a broken wrapper?
A: The old index reports that it has no filter fields.
When a wrapper cannot report support, I stop before searching.
