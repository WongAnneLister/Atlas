# 28 — Long catalog manuals are split like every other section

**What**
I changed how catalog product sections are cut into chunks. A short entry stays one chunk. A manual longer than 512 tokens is now cut into 512-token windows. Each window starts with the product name.

**Why**
The first chunker kept every product section whole. That rule assumed short catalog rows. But four sections hold a whole user manual, up to 12331 tokens. One such chunk can overflow the answer and claim-check budgets.

**Number**
No number yet. I will measure it in the release evidence that follows.

**Trade-off**
The index grows from 210 to 298 chunks in my local preview. A manual fact can now sit in a window without the words around it. I also bumped the chunker version. That forces a full rebuild instead of a cheap incremental one.

**Likely follow-up question**
Q: Why repeat the product name in every window?
A: The reranker and the gate only read the chunk text. A deep window may never name its product. Without the name, a model-number question could fail the gate. The name costs a few tokens per window.
