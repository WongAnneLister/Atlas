# 08 — Rerank and retrieval eval

**What**
I added a reranker after hybrid search. It reads the query and each chunk together.

**Why**
Fast search finds many chunks. The best one is not always first.

**Number**
Recall at 5 went from 0.71 to 0.84 on the dev set. The gain came mostly from model-number questions.
Source: eval/reports/retrieval.md

**Trade-off**
The reranker adds time to every request. I keep only the top 50 chunks to limit it.

**Likely follow-up question**
Q: Why not rerank every chunk?
A: It would be too slow. Fifty chunks already hold the right answer most of the time.
