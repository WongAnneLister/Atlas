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
No number yet. I will measure hit rates, latency saved, and wrong hits with `make eval-cache`.
Offline unit tests already verify key versioning, invalidation, isolation, and Redis failure bypass.

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
