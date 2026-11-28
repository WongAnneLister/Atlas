# 28 — Document and chunks inspector at /chunks

**What**
I added a static `/chunks` page and three read-only API routes. They load local processed documents and saved chunk snapshots at runtime. Clicking any chunk highlights its exact text and overlap spans inside the source document. A top dropdown switches between old and new build snapshots.

**Why**
Chunk size bugs are hard to spot in raw JSON lines. Seeing the source beside its chunks makes split boundaries and overlaps clear. It also lets me compare old oversized manuals against the new split build.

**Number**
No number yet. This page only inspects local files and does not change retrieval or answer quality.

**Trade-off**
The viewer reads local files on each request instead of caching them in memory. That keeps the code small and shows fresh builds right away. It needs local processed files, so a fresh clone sees an empty state.

**Likely follow-up question**
Q: Why load documents from disk at runtime instead of bundling them?
A: Some source texts have unclear third-party licenses and stay gitignored. Loading them at runtime keeps restricted text out of the repository. Every snapshot id is also checked against an allowlist to block path traversal.
