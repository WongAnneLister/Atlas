# 26 — Versioned three-layer caching

**What**
I built three cache layers for embeddings, retrieval results, and knowledge answers.
Every key includes the index build version, filters, prompt version, and model name.
I added strict rules so order data, refunds, and flagged turns never enter the cache.
I also added an evaluation script for replay parity, staleness, isolation, and near-duplicate wrong hits.

**Why**
Customers often ask the same policy and product questions again and again.
Without caching, every repeat turn pays for embedding, reranking, and two model calls.
A naive cache is dangerous because it can serve old policies or another user's data.
Putting versions and customer checks into the design stops those bugs by structure.

**Number**
On 70 smoke questions, mean latency dropped from 13.6034 to 1.9772 seconds.
Tokens fell from 320307 to 191936 with 0 mismatches on 27 answer hits.
Staleness and isolation both passed, and wrong hits were 0 of 20 at 0.97.
Source: eval/reports/cache.md

**Trade-off**
Strict rules leave out multi-part questions and any turn mentioning an order or email.
That lowers the answer cache hit rate on complex conversations.
I kept near-duplicate matching off by default until live tests show zero wrong hits.
This costs some speed, but it prevents wrong model answers and data leaks.

**Likely follow-up question**
Q: What happens if Redis goes down or an index changes?
A: When Redis fails, every layer logs a warning and bypasses the cache.
The request still runs normally and never fails.
When a new index releases, the build version and Redis revision counter both change.
Old retrieval and answer entries miss right away without waiting for expiry.
