# 13 — A paraphrase holdout for retrieval

**What**
I wrote 46 new questions to test the search step. Thirty ask FAQ questions in new words. Sixteen ask about content deep inside long product manuals. I froze them before changing how documents are cut into chunks.

**Why**
Most old test questions copy the FAQ wording, so search looks perfect. Real customers use their own words. The reranker also reads only the first 512 tokens of each chunk. Manual answers far down the page were never tested.

**Number**
The build report lists 46 frozen items. Every manual answer sits far down its manual. I have not measured search on them yet.
Source: eval/reports/paraphrase_holdout.md

**Trade-off**
I wrote the new wording myself, so it may still be easier than real chats. Manual answers are a text window around an anchor phrase. A human should still review the set.

**Likely follow-up question**
Q: Why not just reuse the old test set?
A: It copies the source wording, so it cannot show chunking problems. I needed questions that say the same thing differently.
