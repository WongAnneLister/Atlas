# 26 — Answer cache skips customer context

**What**
I made the answer cache stricter. It now skips any turn whose prompt carries customer memory. It also skips any turn after the first one. I added a graph test with two customers asking the same question.

**Why**
The cache key holds the question, the filters, the index build and the prompt version. The answer prompt also holds the customer profile, pinned facts and earlier turns. So customer A's memory could shape an answer that customer B then gets. The test showed exactly that leak before the fix.

**Number**
No number yet. I will measure it in the next cache report run.

**Trade-off**
Follow-up questions in a chat never hit the cache now. That costs some speed on repeat questions. A leak of one customer's data costs far more. The README already promised single-turn caching, so the code now matches it.

**Likely follow-up question**
Q: Why not add the customer context to the cache key?
A: Then almost no two keys would match. The cache would cost storage and give no hits. Skipping those turns is simpler and easy to test.
