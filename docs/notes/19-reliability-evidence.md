# 19a — Reliability evidence on a clean commit

**What**
I ran the frozen smoke set on the clean commit 19 code.
I also ran it with injected faults: model timeouts and a failing reranker.
A smoke set is a small, fixed group of test questions.

**Why**
Commit 19 must change nothing when every service works.
Under faults, it must hand off instead of guessing.
Two earlier runs failed on network drops and showed two real bugs.
I fixed both bugs before this run.

**Number**
Under faults, the agent answered 0 of 30 questions that have no answer.
It answered 30 of 70 questions and retried 74 times.
It handed off 8 questions because a service was unavailable.
Source: eval/reports/chaos.md

**Trade-off**
Retries and fallbacks make a slow turn even slower.
The circuit breaker now counts whole calls, not single attempts.
That makes it open later, so a dead service fails fast a bit later.

**Likely follow-up question**
Q: Why were the first two runs thrown away?
A: Too many questions failed on network errors, over my 5% limit.
The first run also showed that one unlucky call opened the breaker.
The second showed that some Milvus outages were not retried.
