# 13 — One FAQ per chunk, measured and kept off

**What**
I built a second index with one FAQ question and answer per chunk. Product manuals became short windows that start with the product name. The reranker now drops chunks with identical text. The default still uses the old index, because the full test failed on safety.

**Why**
Old chunks held many FAQs, so a reworded question scored low. The reranker reads only 512 tokens, but some manual answers sat much deeper. A chunk is a piece of text the search returns.

**Number**
On v1, unanswerable questions answered rose from 1 to 5 of 106. On v2, they rose from 0 to 1 of 35. Deep manual questions were answered 15 and 14 times, against 11 and 14 before. Median dev input tokens fell from 2918 to 1546.
Source: eval/reports/chunking_e2e.md

**Trade-off**
Smaller chunks gave the model cleaner text, so it answered more. Some of those answers relied on a fact being missing. I kept the safe default and lost the token saving for now.

**Likely follow-up question**
Q: Retrieval got better, so why not ship it?
A: My rule is zero wrong answers on questions with no answer. Retrieval tests alone missed this. The full graph run showed it, so I kept the old default.
