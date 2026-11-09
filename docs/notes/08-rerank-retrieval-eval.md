# 08 — Cross-encoder rerank and retrieval evaluation

**What**
I built a reranker that reads each question beside each search result.
I compared meaning search, word search, their merge, and reranking.
I also tested heading prefixes and model spelling cleanup.

**Why**
Merged ranks can still put weak evidence first.
I needed a repeatable comparison before adding checks that can block unsupported answers.
I kept the frozen questions and labels unchanged.

**Number**
Recall@5 measures how much required evidence appears in the first five results.
My reranked test Recall@5 reached 1.0000.
MRR@5 rewards useful results appearing earlier in the first five slots.
My reranked test MRR@5 reached 0.9938.
Source: eval/reports/retrieval.md

**Trade-off**
I traded speed for stronger ordering.
Long manuals still lose text at the model's length limit.
I processed small groups of results to fit local memory.

**Likely follow-up question**
Q: Does perfect test recall mean this system is ready?
A: I still need human review of the questions.
The draft test set cannot prove answer safety.
My development failures still lose one part of combined questions.
I will test keeping results from more distinct sections.
