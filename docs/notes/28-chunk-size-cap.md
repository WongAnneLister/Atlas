# 28 — Builds fail on any chunk over a hard size cap

**What**
I added a hard cap on chunk size at build time. If any chunk is over 4096 tokens, the build stops. The error lists each chunk id, its section and its size. Every build also records its largest and 99th-percentile chunk size.

**Why**
The old index held four whole manuals in single chunks. Nothing checked chunk sizes after building. So a 512-token rule was never really enforced. The problem only showed up much later, as an overflowing prompt.

**Number**
No number yet. I will measure it in the evidence commit that follows.

**Trade-off**
A build can now fail on data that used to load. I chose a loud failure over silent truncation. Cutting text would hide facts from the answer. The cap does not yet block a release by itself.

**Likely follow-up question**
Q: Why fail the build instead of just splitting the big chunk?
A: The splitter is supposed to make that chunk impossible. If one appears, the rules have a bug. A failed build points at the exact chunk. Quietly fixing it would hide the bug.
