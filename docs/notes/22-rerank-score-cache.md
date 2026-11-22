# 22c — Rerank score cache

**What**
I added a local cache of reranker scores for the index release check. A reranker is a model that scores each question and passage pair. Each score's key holds the model, version, device and settings. It also holds the question and a passage hash.

**Why**
A release check scores about 50 passages for each of 220 questions. After a small document change, almost every pair is the same as before. Without the cache, I paid for all those scores again. One release side took about half an hour on the GPU.

**Number**
For a one-section change, the check took 25.8 minutes without the cache. With a warm cache, it took 6.6 minutes. It reused 10,915 of 11,000 scores. Metrics and top-5 lists matched on all 220 questions.
Source: eval/reports/rerank_cache.md

**Trade-off**
Four gate scores moved by at most 7.13e-09. The new pairs ran in smaller batches, so the float math changed slightly. No decision changed. The cache also has no size limit, and its first use starts cold.

**Likely follow-up question**
Q: How do you know the cache never gives a wrong score?
A: Anything that can change a score is part of the key. A different model, device or passage text is a miss, and tests check each one. A test also compares a cached run with an uncached run. The real run matched on every metric.
