# 24c — Faster end-to-end eval runs

**What**
I added two opt-in speed switches to the full-graph evaluators. The first reuses cached reranker scores. A reranker is a model that scores each question and passage pair. The second runs several questions at once, up to a set limit.

**Why**
One question takes about 17 seconds with real models. The next evidence commit needs about 900 question runs. That is hours of waiting. Most runs score the same pairs again, and questions ran one at a time.

**Number**
No number yet. I will measure it in commit 24b.

**Trade-off**
Parallel questions share the GPU and the API, so latency includes waiting. I mark that latency as not comparable, and comparisons skip it. A long reranker queue can also hit its timeout. So I keep the worker limit small.

**Likely follow-up question**
Q: How do you know the speed-ups do not change the results?
A: The cache key is the same as the release check's key. On test fixtures, cached and uncached scores are identical. Saved results keep the input order, not the finish order. Both switches stay out of the config hash.
